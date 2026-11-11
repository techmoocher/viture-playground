/*
 * capture_shim.c — native capture of VITURE SDK IMU callbacks for headmusic.
 *
 * Why this exists (docs/phase1-proposal.md §3.5): a Python ctypes callback must acquire the GIL
 * on the SDK's IMU thread. Under Python load this blocked the SDK thread, lost 58% of samples
 * upstream and delayed the rest by ~0.3 s. This shim handles the callback in native code:
 *   - host receipt time = QueryPerformanceCounter scaled to ns (same timebase as Python's
 *     time.perf_counter_ns), taken as the first statement of the callback;
 *   - the SDK values and timestamps are copied verbatim (no conversion);
 *   - records go into a fixed-size ring buffer; Python drains it with cap_read();
 *   - every callback gets a sequence number before the overflow check, so overflow shows up
 *     downstream as a seq gap as well as in the overflow counter.
 *
 * Producers: SDK callback threads (a spin lock makes concurrent producers safe).
 * Consumer:  exactly one thread calling cap_read().
 * The shim has no dependency on the SDK headers; it only matches the callback signatures:
 *   pose: void(float* data, uint64_t timestamp)                 data[7]
 *   raw:  void(float* data, uint64_t timestamp, uint64_t vsync)  data[10]
 *
 * Build: native/build_shim.sh (MinGW-w64 in WSL). C11, no C runtime objects cross the API.
 */
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>

#define CAP_ABI_VERSION 1u
#define CAP_RING_SIZE 65536u /* power of two; ~5 min at 200 Hz */
#define CAP_MAX_VALUES 10u

#define CAP_KIND_POSE 1u
#define CAP_KIND_RAW 2u

typedef struct {
    uint64_t seq;       /* callback sequence number since cap_reset (pose and raw share it) */
    int64_t host_ns;    /* QPC-based ns at callback entry */
    uint64_t device_ts; /* SDK timestamp, verbatim */
    uint64_t vsync;     /* raw callbacks only, verbatim; 0 for pose */
    float v[CAP_MAX_VALUES];
    uint32_t kind;      /* CAP_KIND_* */
    uint32_t n_values;  /* 7 (pose) or 10 (raw); 0 if the SDK passed a NULL data pointer */
} cap_record_t;         /* 80 bytes */

typedef struct {
    uint64_t total;            /* callbacks captured (both kinds) */
    uint64_t overflow;         /* records dropped because the ring was full */
    uint64_t high_water;       /* maximum ring occupancy observed */
    uint64_t count_only_pose;  /* pose callbacks received by the count-only handler */
    uint64_t count_only_raw;   /* raw callbacks received by the count-only handler */
} cap_stats_t;

static cap_record_t g_ring[CAP_RING_SIZE];
static _Atomic uint64_t g_head, g_tail, g_seq, g_overflow, g_high_water, g_count_pose, g_count_raw;
static atomic_flag g_producer_lock = ATOMIC_FLAG_INIT;
static int64_t g_qpf = 0;

static int64_t qpc_ns(void) {
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    const int64_t t = c.QuadPart;
    /* Split to avoid overflow; identical scaling to CPython's perf_counter_ns on Windows. */
    return (t / g_qpf) * 1000000000LL + (t % g_qpf) * 1000000000LL / g_qpf;
}

static void push(uint32_t kind, const float* d, uint32_t n, uint64_t ts, uint64_t vsync, int64_t t) {
    while (atomic_flag_test_and_set_explicit(&g_producer_lock, memory_order_acquire)) {
        /* spin: producers are SDK threads; contention is not expected */
    }
    const uint64_t seq = atomic_fetch_add_explicit(&g_seq, 1, memory_order_relaxed);
    const uint64_t head = atomic_load_explicit(&g_head, memory_order_relaxed);
    const uint64_t used = head - atomic_load_explicit(&g_tail, memory_order_acquire);
    if (used >= CAP_RING_SIZE) {
        atomic_fetch_add_explicit(&g_overflow, 1, memory_order_relaxed);
    } else {
        cap_record_t* r = &g_ring[head & (CAP_RING_SIZE - 1u)];
        r->seq = seq;
        r->host_ns = t;
        r->device_ts = ts;
        r->vsync = vsync;
        memset(r->v, 0, sizeof r->v);
        if (d) {
            memcpy(r->v, d, n * sizeof(float));
            r->n_values = n;
        } else {
            r->n_values = 0;
        }
        r->kind = kind;
        atomic_store_explicit(&g_head, head + 1, memory_order_release);
        if (used + 1 > atomic_load_explicit(&g_high_water, memory_order_relaxed)) {
            atomic_store_explicit(&g_high_water, used + 1, memory_order_relaxed);
        }
    }
    atomic_flag_clear_explicit(&g_producer_lock, memory_order_release);
}

static void pose_capture_cb(float* d, uint64_t ts) {
    const int64_t t = qpc_ns();
    push(CAP_KIND_POSE, d, 7u, ts, 0u, t);
}

static void raw_capture_cb(float* d, uint64_t ts, uint64_t vsync) {
    const int64_t t = qpc_ns();
    push(CAP_KIND_RAW, d, 10u, ts, vsync, t);
}

static void pose_count_cb(float* d, uint64_t ts) {
    (void)d; (void)ts;
    atomic_fetch_add_explicit(&g_count_pose, 1, memory_order_relaxed);
}

static void raw_count_cb(float* d, uint64_t ts, uint64_t vsync) {
    (void)d; (void)ts; (void)vsync;
    atomic_fetch_add_explicit(&g_count_raw, 1, memory_order_relaxed);
}

__declspec(dllexport) uint32_t cap_abi_version(void) { return CAP_ABI_VERSION; }
__declspec(dllexport) uint32_t cap_record_size(void) { return (uint32_t)sizeof(cap_record_t); }
__declspec(dllexport) uint32_t cap_ring_size(void) { return CAP_RING_SIZE; }

/* Must only be called while no SDK callback can fire (before registering / after destroy). */
__declspec(dllexport) void cap_reset(void) {
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    g_qpf = f.QuadPart;
    atomic_store(&g_head, 0);
    atomic_store(&g_tail, 0);
    atomic_store(&g_seq, 0);
    atomic_store(&g_overflow, 0);
    atomic_store(&g_high_water, 0);
    atomic_store(&g_count_pose, 0);
    atomic_store(&g_count_raw, 0);
}

__declspec(dllexport) int64_t cap_now_ns(void) { return qpc_ns(); }

__declspec(dllexport) void* cap_pose_capture_callback(void) { return (void*)pose_capture_cb; }
__declspec(dllexport) void* cap_raw_capture_callback(void) { return (void*)raw_capture_cb; }
__declspec(dllexport) void* cap_pose_count_callback(void) { return (void*)pose_count_cb; }
__declspec(dllexport) void* cap_raw_count_callback(void) { return (void*)raw_count_cb; }

/* Copy up to max records into out; returns the number copied. Single consumer only. */
__declspec(dllexport) int cap_read(cap_record_t* out, int max) {
    if (!out || max <= 0) return 0;
    uint64_t tail = atomic_load_explicit(&g_tail, memory_order_relaxed);
    const uint64_t head = atomic_load_explicit(&g_head, memory_order_acquire);
    int n = 0;
    while (tail != head && n < max) {
        out[n++] = g_ring[tail & (CAP_RING_SIZE - 1u)];
        ++tail;
    }
    atomic_store_explicit(&g_tail, tail, memory_order_release);
    return n;
}

__declspec(dllexport) void cap_stats(cap_stats_t* out) {
    if (!out) return;
    out->total = atomic_load(&g_seq);
    out->overflow = atomic_load(&g_overflow);
    out->high_water = atomic_load(&g_high_water);
    out->count_only_pose = atomic_load(&g_count_pose);
    out->count_only_raw = atomic_load(&g_count_raw);
}
