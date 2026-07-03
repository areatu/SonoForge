# Benchmark Baseline

**Date:** 2026-07-03
**Hardware:** Windows dev machine (Python 3.11.9, pytest-benchmark 5.2.3)
**Command:** `ECHO_BENCH=1 pytest tests/bench -v --benchmark-warmup=off --benchmark-min-rounds=3 --benchmark-only`

Use this file to compare performance across machines. Re-run benchmarks on the target system and update the "Target" column.

---

## Decode / DICOM Session

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `decode_uncompressed_zero_copy` | 218 µs | 224 µs | 231 µs | 4,325 | 1,580 | np.frombuffer view, 10 frames 256×256 uint16 |
| `decode_uncompressed_with_copy` | 424 µs | 436 µs | 454 µs | 2,202 | 1,159 | np.frombuffer + .copy(), same data |
| `dicom_session_open` | 3.43 ms | 3.71 ms | 3.78 ms | 265 | 172 | DicomSession.open() full parse |
| `dicom_session_decode_uncompressed` | 1.10 µs | 1.40 µs | 1.44 µs | 695K | 83 | Session decode uncompressed fragment |
| `dicom_session_decode_jpeg` | 1.10 µs | 1.10 µs | 1.19 µs | 838K | 79 | Session decode JPEG fragment |
| `dicom_session_decode_jpeg2000` | 1.10 µs | 1.10 µs | 1.32 µs | 758K | 32 | Session decode JPEG2000 fragment |
| `dicom_session_single_frame_random_access` | 62.2 µs | 64.5 µs | 69.0 µs | 14,499 | 146 | Random access single frame |
| `decode_fragment_jpeg_cv2` | 2.30 ms | 2.39 ms | 2.46 ms | 406 | 341 | OpenCV JPEG decode fragment |
| `decode_fragment_jpeg2000_single` | 42.5 ms | 43.2 ms | 43.2 ms | 23.1 | 24 | JPEG2000 single fragment decode |
| `pydicom_pixel_array_fallback` | 2.68 ms | 3.08 ms | 3.17 ms | 316 | 238 | pydicom pixel_array fallback path |

## Frame Cache / Eviction

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `frame_cache_get` | 360 ns | 440 ns | 516 ns | 1.94M | 147,059 | Single get() on loaded frame |
| `frames_property_first_call` | 79.3 µs | 102 µs | 106 µs | 9,413 | 8,313 | np.stack rebuild (60 frames 16×16) |
| `frames_property_cached` | 330 ns | 370 ns | 393 ns | 2.54M | 178,572 | Cached result return |
| `sorted_keys_eviction_logic` | 37.3 µs | 41.0 µs | 43.6 µs | 22,930 | 2,024 | bisect-based eviction, 500 frames |
| `evict_200_frames_sweep` | 7.60 µs | 8.70 µs | 9.35 µs | 106,931 | 7,764 | set_current sweep over 200-frame cache |
| `evict_with_pinned_frames` | 31.4 µs | 34.7 µs | 36.9 µs | 27,100 | 11,508 | 50 pinned frames, evict guard overhead |

## Playback Pipeline

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `playback_fps_30_frame_loop` | 49.1 µs | 54.1 µs | 56.5 µs | 17,686 | 11,905 | 30-frame get+set_current sweep |
| `playback_fps_100_frame_loop` | 168 µs | 186 µs | 195 µs | 5,138 | 5,328 | 100-frame loop, evict_window=100 |
| `prefetch_batch_load` | 3.80 µs | 4.20 µs | 4.52 µs | 221,202 | 45,249 | put() 8 frames into cache |
| `small_loop_full_prefetch` | 5.80 µs | 6.20 µs | 6.64 µs | 150,620 | 86,207 | List comprehension for 45-frame cine |
| `warmup_loaded_ahead_count` | 27.7 µs | 29.2 µs | 30.9 µs | 32,323 | 25,446 | loaded_ahead() sweep over 60 frames |
| `double_next_skip_check` | 9.60 µs | 10.7 µs | 11.1 µs | 90,146 | 59,524 | is_loaded(next) + is_loaded(next+1) loop |

## Scroll / Navigation

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `scroll_single_frame_hit` | 2.40 µs | 2.60 µs | 2.76 µs | 362,931 | 153,847 | set_current + get, cache hit |
| `scroll_single_frame_miss` | 2.10 µs | 2.30 µs | 2.41 µs | 414,856 | 43,669 | set_current to evicted frame |
| `scroll_rapid_forward_20` | 26.1 µs | 29.4 µs | 30.9 µs | 32,329 | 27,473 | 20 consecutive forward set_current |
| `scroll_rapid_backward_20` | 26.1 µs | 29.1 µs | 30.6 µs | 32,647 | 24,450 | 20 consecutive backward set_current |
| `directional_prefetch_forward` | 78.0 µs | 81.6 µs | 87.2 µs | 11,462 | 9,364 | loaded_ahead + nearest_loaded_ahead sweep |
| `directional_prefetch_backward` | 72.8 µs | 76.7 µs | 83.3 µs | 12,009 | 11,416 | loaded_before + nearest_loaded_before sweep |

## Playback FPS — Real DICOM (800×1276, 124 frames, 30 FPS)

| Benchmark | Median | Mean | OPS | Notes |
|-----------|--------|------|-----|-------|
| `real_fps_hot_cache` | 227 µs | 234 µs | 4,273 | All 124 frames cached |
| `real_fps_pin_cycle` | 288 µs | 298 µs | 3,350 | + pin/unpin per frame |
| `real_fps_forward_backward` | 449 µs | 466 µs | 2,146 | Forward + backward loop |
| `real_fps_warmup_check` | 575 µs | 610 µs | 1,640 | loaded_ahead + is_loaded |
| `real_fps_partial_cache` | 211 µs | 219 µs | 4,573 | Only 30/124 frames cached |
| `real_single_frame_decode` | 350 ns | 363 ns | 2,756K | cache.put() overhead |

**Key insight:** Real DICOM (800×1276) has **same tick overhead** as synthetic 256×256 — pixel data size is irrelevant for cache-only playback. Theoretical max ~4,400 FPS; real FPS is bottlenecked by Qt timer + frame decode + render.

## Playback FPS Pipeline (synthetic)

| Benchmark | Min | Median | Mean | OPS | Notes |
|-----------|-----|--------|------|-----|-------|
| `fps_hot_cache_64` | 249 µs | 266 µs | 277 µs | 3,607 | 64×64, 60 frames, all cached |
| `fps_hot_cache_256` | 249 µs | 265 µs | 273 µs | 3,667 | 256×256, 60 frames, all cached |
| `fps_hot_cache_512` | 250 µs | 266 µs | 275 µs | 3,634 | 512×512, 60 frames, all cached |
| `fps_forward_backward` | 94 µs | 105 µs | 108 µs | 9,290 | 30 fwd + 30 bwd, 256×256 |
| `fps_warmup_check` | 152 µs | 161 µs | 172 µs | 5,819 | loaded_ahead + is_loaded sweep |
| `fps_large_cine_200` | 336 µs | 372 µs | 383 µs | 2,614 | 200 frames, all cached |
| `fps_pin_cycle` | 125 µs | 137 µs | 140 µs | 7,124 | pin/unpin per frame |
| `fps_report_256` | 97 µs | 107 µs | 109 µs | 9,188 | 256×256, 60 frames |

**Key findings:**
- Frame size has **negligible impact** on tick overhead (64 vs 512 ≈ same ~265 µs)
- The bottleneck is `set_current()` + `get()` dict lookups, not pixel data
- 60-frame hot-cache loop runs in ~265 µs → theoretical max **~3,700 FPS** (cache-only)
- Pin/unpin adds ~33 µs overhead per frame (140 vs 107 µs)
- 200-frame cine is 1.4x slower due to larger `_sorted_keys` bisect

## Rendering

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `wl_lut` (viewer_perf) | 7.95 ms | 10.3 ms | 10.6 ms | 94.4 | 90 | W/L LUT on 512×512 uint16 |
| `wl_lut_uint16` | 10.3 ms | 10.8 ms | 10.9 ms | 91.4 | 93 | W/L LUT on 512×512 uint16 |
| `wl_lut_uint8` | 9.10 ms | 9.67 ms | 9.71 ms | 103 | 47 | W/L LUT on 512×512 uint8 |
| `wl_legacy` | 11.2 ms | 13.2 ms | 14.3 ms | 69.8 | 68 | Legacy float percentile path |
| `to_grayscale_uint8` | 78.1 µs | 80.2 µs | 85.4 µs | 11,707 | 208 | BGR → grayscale, 512×512 |
| `to_grayscale_array_float64` | 956 µs | 1,080 µs | 1,115 µs | 897 | 831 | Full float64 grayscale, 512×512 |
| `to_display_rgb` | 1.70 ms | 1.77 ms | 1.87 ms | 534 | 406 | BGR → RGB for color Doppler, 512×512 |
| `color_frame_detection` | 43.6 ms | 45.0 ms | 45.4 ms | 22.0 | 22 | is_color_frame × 100 calls |
| `grayscale_check` | 43.3 ms | 44.8 ms | 44.8 ms | 22.3 | 22 | is_effective_grayscale × 100 calls |

## Thumbnail / Pipeline

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `thumbnail_decode_single` | 2.30 µs | 2.50 µs | 2.66 µs | 376,196 | 177 | Single thumbnail decode |
| `first_frame_latency` | 19.1 ms | 21.4 ms | 21.9 ms | 45.8 | 54 | Full pipeline first frame |
| `scanworker_dispatch` | 8.99 ms | 9.63 ms | 9.68 ms | 103 | 37 | ScanWorker dispatch overhead |
| `scan_small_study` | 9.00 ms | 9.79 ms | 9.84 ms | 102 | 39 | Scan small study (synthetic) |
| `scan_large_study` | 13.8 ms | 14.7 ms | 15.1 ms | 66.1 | 71 | Scan large study (synthetic) |
| `scan_study_multiframe` | 8.85 ms | 9.46 ms | 9.71 ms | 103 | 98 | Multiframe study scan |
| `pipeline_uncompressed_decode` | 15.6 ms | 17.2 ms | 17.3 ms | 57.7 | 57 | Full pipeline uncompressed |
| `pipeline_jpeg_decode` | 6.27 ms | 6.97 ms | 7.08 ms | 141 | 127 | Full pipeline JPEG |
| `pipeline_jpeg2000_decode` | 31.3 ms | 33.0 ms | 32.9 ms | 30.4 | 32 | Full pipeline JPEG2000 |

## Network (Fake clients)

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `dimse_c_echo_fake` | 139 ns | 148 ns | 158 ns | 6.34M | 192,308 | FakeDimseClient.c_echo() |
| `dimse_c_find_studies_fake` | 440 ns | 480 ns | 500 ns | 2.00M | 90,091 | FakeDimseClient.c_find_studies() |
| `dimse_c_find_studies_filtered` | 1.70 µs | 1.90 µs | 2.03 µs | 492,804 | 153,847 | c_find_studies(patient_name="DOE") |
| `dimse_c_find_series_fake` | 315 ns | 345 ns | 369 ns | 2.71M | 103,093 | c_find_series() |
| `dimse_c_find_instances_fake` | 335 ns | 370 ns | 392 ns | 2.55M | 55,249 | c_find_instances() |
| `dimse_c_store_fake` | 145 ns | 155 ns | 164 ns | 6.10M | 185,186 | c_store(4KB) |
| `web_query_studies` | 5.40 µs | 5.70 µs | 6.13 µs | 163,019 | 835 | FakeDicomWebClient.query_studies() |
| `web_query_studies_filtered` | 6.20 µs | 6.60 µs | 7.10 µs | 140,750 | 4,087 | query_studies(patient_name="DOE") |
| `web_query_series` | 5.10 µs | 5.30 µs | 6.03 µs | 165,834 | 863 | query_series() |
| `web_stow_instances` | 1.70 µs | 1.90 µs | 2.02 µs | 494,087 | 135,136 | stow_instances(5×2KB) |
| `query_service_auto` | 7.60 µs | 8.10 µs | 8.89 µs | 112,447 | 5,471 | DicomQueryService AUTO mode |
| `query_service_dimse_only` | 1.90 µs | 2.10 µs | 2.30 µs | 435,726 | 149,254 | DicomQueryService DIMSE-only |
| `query_service_series` | 5.70 µs | 6.00 µs | 6.41 µs | 156,072 | 3,978 | query_series delegation |
| `stow_multipart_1_file` | 31.5 µs | 33.5 µs | 34.8 µs | 28,745 | 20,534 | Multipart body build, 1 file |
| `stow_multipart_10_files` | 316 µs | 328 µs | 342 µs | 2,921 | 2,666 | Multipart body build, 10 files |
| `stow_multipart_50_files` | 3.56 ms | 4.23 ms | 4.36 ms | 230 | 266 | Multipart body build, 50 files |

## Memory

| Benchmark | Min | Median | Mean | OPS | Rounds | Notes |
|-----------|-----|--------|------|-----|--------|-------|
| `mem_30_frame_cine` | 393 µs | 413 µs | 436 µs | 2,293 | 1,857 | Load + sweep 30-frame cine (256×256 uint16) |
| `mem_200_frame_cine` | 542 µs | 565 µs | 600 µs | 1,667 | 1,069 | Load + sweep 200-frame cine (128×128 uint16) |
| `memory_bytes_tracking` | 24.5 µs | 26.4 µs | 27.6 µs | 36,182 | 6,619 | memory_bytes() call during playback |
| `zero_copy_view_lifetime` | 174 µs | 181 µs | 188 µs | 5,331 | 3,975 | 100 × np.frombuffer views (256×256) |
| `heap_copy_allocation` | 3.55 ms | 4.43 ms | 4.51 ms | 222 | 271 | 100 × frombuffer + copy (256×256) |
| `eviction_reclaims_memory` | 7.60 µs | 8.10 µs | 8.62 µs | 115,964 | 13,478 | Verify memory_bytes() drops after evict |

---

## Key Takeaways

1. **Zero-copy decode is ~2x faster** than copy path — 224 µs vs 436 µs.
2. **FrameCache.get() is sub-microsecond** — 440 ns median.
3. **Scroll single-frame latency is ~2.5 µs** — both hit and miss paths.
4. **W/L LUT is ~10 ms** on 512×512 — higher than Linux baseline (~4 ms), likely platform-dependent.
5. **STOW multipart scales linearly** — ~6.5 µs/file on average.
6. **FakeDimseClient C-ECHO is ~148 ns** — negligible overhead.
7. **JPEG2000 decode is the bottleneck** — 33–43 ms per call, dominates pipeline.
8. **color_frame_detection and grayscale_check are ~45 ms** each — candidates for optimization.

## How to Re-run

```bash
# Full suite
ECHO_BENCH=1 pytest tests/bench/ -v --benchmark-only --benchmark-warmup=off --benchmark-min-rounds=3

# Single category
ECHO_BENCH=1 pytest tests/bench/test_playback_bench.py --benchmark-only

# Compare with saved baseline
ECHO_BENCH=1 pytest tests/bench/ --benchmark-only --benchmark-compare=0001
```
