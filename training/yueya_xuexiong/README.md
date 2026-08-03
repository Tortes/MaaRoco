# Yueya Xuexiong Training

This directory builds a one-class YOLO11 detector for `yueya_xuexiong`.

## Two-stage training

1. `synthetic`: paste the encyclopedia cutout onto real game backgrounds. Labels are exact and the stage rapidly learns the silhouette.
2. `mixed`: fine-tune the synthetic checkpoint using reviewed in-game frames and known negatives such as blue grass and green interaction objects.

The encyclopedia art and public-video cover are stored as source provenance only. Video frames must be reviewed and labeled before training.

## Commands

Run every command from the repository root.

```powershell
python tools/yueya_xuexiong_pipeline.py bootstrap
python tools/yueya_xuexiong_pipeline.py extract-template
python tools/yueya_xuexiong_pipeline.py synthesize --count 400
python tools/yueya_xuexiong_pipeline.py prepare --stage synthetic
python tools/yueya_xuexiong_pipeline.py train --stage synthetic --epochs 40
python tools/yueya_xuexiong_pipeline.py prepare --stage mixed
python tools/yueya_xuexiong_pipeline.py train --stage mixed --epochs 40
python tools/yueya_xuexiong_pipeline.py export
```

The training script chooses CUDA device 0 when the installed PyTorch build exposes it. Otherwise it uses CPU for a smoke run only.

## Inference

Template matching is an immediate baseline for art that is very close to the
encyclopedia sprite or the synthetic samples. It uses the sprite alpha as a mask
and searches across scales.

```powershell
python tools/yueya_xuexiong_pipeline.py detect-template D:\path\to\image.png
```

For actual game frames, use the mixed YOLO checkpoint after fine-tuning. The
command writes an annotated preview under `work/inference/` and prints each box.

```powershell
python tools/yueya_xuexiong_pipeline.py detect-yolo D:\path\to\image.png
```

## Real frames

Place a downloaded public video at a local path and extract one frame per second:

```powershell
python tools/yueya_xuexiong_pipeline.py extract-video D:\path\to\video.mp4
```

Review the extracted frames, keep frames containing Yueya Xuexiong, and create a matching YOLO `.txt` file next to each image before copying the pair into `sources/real/`. Empty `.txt` files belong in `sources/negatives/` for blue grass, green interaction objects, terrain, UI, and other blue creatures.

The model is exported to `models/yueya_xuexiong.onnx` after the mixed stage.

## Clean v2 retraining

`clean_v2` discards the old clustered real-image annotations. It uses only the
individually boxed screenshots listed in `clean_v2_annotations.json`, plus the
explicit blue-grass and terrain negatives. The split is fixed so adjacent or
repeated files cannot move between train and validation by chance.

The default validation set contains eight real game screenshots and two
single-object synthetic images. Generated images therefore account for 20% of
validation instead of dominating the regression score.

```powershell
python tools/yueya_xuexiong_pipeline.py synthesize --count 60 --seed 20260803
python tools/yueya_xuexiong_pipeline.py prepare --stage clean_v2
python tools/yueya_xuexiong_pipeline.py train --stage clean_v2 --epochs 120 --imgsz 768 --batch 8
python tools/yueya_xuexiong_pipeline.py export --weights training/yueya_xuexiong/models/yueya_xuexiong_clean_v2.pt --imgsz 768
```

Training starts from the generic `yolo11n.pt` checkpoint and never reuses the
previous synthetic or mixed snow-bear checkpoints.
