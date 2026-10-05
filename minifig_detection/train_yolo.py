import random
from pathlib import Path

import yaml
from ultralytics import YOLO

# Path to the Roboflow-exported dataset folder. Either the split layout
# (data.yaml + train/, valid/, test/) or a flat one (data.yaml + images/,
# labels/), which gets split into train/val automatically.
DATASET_DIR = Path(__file__).parent / "BlueFig"

# Where training runs (weights, logs, plots) get written.
RUNS_DIR = Path(__file__).parent / "runs"
RUN_NAME = "blue_detector"

# Pretrained weights to start from. "yolov8n.pt" (nano) is fastest and
# works well for small datasets; swap for "yolov8s.pt" for more accuracy
# at the cost of slower training.
BASE_WEIGHTS = "yolov8n.pt"

EPOCHS = 50
IMAGE_SIZE = 512  # matches the 512x512 resize Roboflow already applied

# Fraction of images held out for validation when the dataset is flat.
VAL_FRACTION = 0.2
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def split_flat_dataset(dataset_dir):
    """For a flat export (no train/valid folders), write train.txt and val.txt
    listing a fixed random split of the labeled images. Images without a
    matching label file are skipped.
    """
    # Images and labels may sit in images/ + labels/ or loose side by side.
    image_dir = dataset_dir / "images"
    label_dir = dataset_dir / "labels"
    if not image_dir.exists():
        image_dir = label_dir = dataset_dir
    images = sorted(
        p for p in image_dir.iterdir()
        if p.suffix.lower() in IMAGE_SUFFIXES
        and (label_dir / f"{p.stem}.txt").exists()
    )
    if len(images) < 2:
        raise ValueError(f"Need at least 2 labeled images in {dataset_dir}")

    random.Random(0).shuffle(images)
    n_val = max(1, round(len(images) * VAL_FRACTION))
    splits = {"val.txt": images[:n_val], "train.txt": images[n_val:]}
    for name, paths in splits.items():
        (dataset_dir / name).write_text("\n".join(str(p) for p in paths) + "\n")
    print(f"Split {len(images)} labeled images: "
          f"{len(images) - n_val} train, {n_val} val")
    return "train.txt", "val.txt"


def build_absolute_data_yaml(dataset_dir):
    """Roboflow's exported data.yaml uses '../train/images'-style paths
    that assume a different folder layout than a flat extracted zip.
    Read the class info out of it and rewrite train/val/test as absolute
    paths pointing at this exact dataset folder, so training works
    regardless of where the dataset lives on disk.
    """
    source_yaml = dataset_dir / "data.yaml"
    with open(source_yaml) as f:
        config = yaml.safe_load(f)

    config["path"] = str(dataset_dir)
    if (dataset_dir / "train" / "images").exists():
        config["train"] = "train/images"
        config["val"] = "valid/images"
        if (dataset_dir / "test" / "images").exists():
            config["test"] = "test/images"
    else:
        config["train"], config["val"] = split_flat_dataset(dataset_dir)
        config.pop("test", None)

    resolved_yaml = Path(__file__).parent / "dataset.yaml"
    with open(resolved_yaml, "w") as f:
        yaml.safe_dump(config, f)
    return resolved_yaml


def main():
    if not (DATASET_DIR / "data.yaml").exists():
        raise FileNotFoundError(
            f"Couldn't find data.yaml in {DATASET_DIR}. "
            "Update DATASET_DIR to point at your extracted Roboflow dataset."
        )

    data_yaml = build_absolute_data_yaml(DATASET_DIR)
    print(f"Using dataset config: {data_yaml}")

    model = YOLO(BASE_WEIGHTS)
    results = model.train(
        data=str(data_yaml),
        epochs=EPOCHS,
        imgsz=IMAGE_SIZE,
        project=str(RUNS_DIR),
        name=RUN_NAME,
    )

    best_weights = Path(results.save_dir) / "weights" / "best.pt"
    print(f"\nTraining complete. Best weights saved to: {best_weights}")


if __name__ == "__main__":
    main()
