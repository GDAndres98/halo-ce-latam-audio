# Migration `eco_effect` (20261013T150942_eco_effect)

Owner-authorized (2026-10-13): Spain intercom EQ + Spain echo on the "eco" radio lines; approved audio set to needs rework; matches kept. Mode: **write**.

- Preset: `{"radio": {"low_hz": 350, "high_hz": 8000, "slope_db_oct": 36, "presence_db": 8, "presence_hz": 2500, "drive_db": 0, "noise_dbfs": null, "clicks": false, "preset": "spain_eco"}, "echo": {"slap_ms": 30, "slap_db": null, "delay_ms": 140, "echo_db": -11, "feedback_db": -15, "diffusion": 1, "damping_hz": 4000, "preset": "spain"}}`
- Changed: **18**; skipped: 0.
- File before: `7598f2666cd76aa47031cbd0b171d57ef902afcf4b4f904c93c5b9507ee5aa7b`; after: `a60b3f737eb2e151d8a823c07e85334be98500bb930d60ebe79325e3fea2bdfd`

| Mapping | Slot | Audio before → after | Recipe |
|---|---|---|---|
| `m-000002` | `es:A10_011_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000004` | `es:A10_030_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000007` | `es:A10_051_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000016` | `es:A10_160_cryoassist#0` | approved → needs_rework (rev 3) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000017` | `es:A10_170_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000018` | `es:A10_180_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000019` | `es:A10_190_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000020` | `es:A10_200_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000021` | `es:A10_210_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000022` | `es:A10_220_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000023` | `es:A10_230_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000028` | `es:A10_320_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000030` | `es:A10_340_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000036` | `es:A10_400_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000038` | `es:A10_420_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000039` | `es:A10_430_Cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000040` | `es:A10_440_cryoassist#0` | approved → needs_rework (rev 2) | radio spain_eco 350–8000 Hz · echo spain 140 ms |
| `m-000133` | `es:ass03#0` | approved → needs_rework (rev 3) | 2 cuts (1.53 s) · radio spain_eco 350–8000 Hz · echo spain 140 ms |

## Verification

- written_sha_matches: True
- result_equals_plan: True
- only_audio_of_targets_changed: True
- every_target_has_the_effect: True
- none_left_approved: True
- idempotent_second_pass_changes_nothing: True
