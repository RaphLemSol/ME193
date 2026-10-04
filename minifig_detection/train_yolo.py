from pathlib import Path

import yaml
from ultralytics import YOLO

# Path to the Roboflow-exported dataset folder (contains data.yaml,
# train/, valid/, test/). Defaults to the copy checked into this repo;
# edit this if you point at a different dataset.
DATASET_DIR = Path(__file__).parent / "dataset"

# Where training runs (weights, logs, plots) get written.
RUNS_DIR = Path(__file__).parent / "runs"
RUN_NAME = "minifig_detector"

# Pretrained weights to start from. "yolov8n.pt" (nano) is fastest and
# works well for small datasets; swap for "yolov8s.pt" for more accuracy
# at the cost of slower training.
BASE_WEIGHTS = "yolov8n.pt"

EPOCHS = 50
IMAGE_SIZE = 512  # matches the 512x512 resize Roboflow already applied


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
    config["train"] = "train/images"
    config["val"] = "valid/images"
    if (dataset_dir / "test" / "images").exists():
        config["test"] = "test/images"

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
