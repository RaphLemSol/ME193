"""
FingerNet: the convolutional neural net (PyTorch) that counts fingers.

    input (3, 64, 64) color picture of the taped square
    conv1  16 filters 5x5 -> ReLU -> 2x2 max pool   (16, 32, 32)
    conv2  32 filters 3x3 -> ReLU -> 2x2 max pool   (32, 16, 16)
    conv3  64 filters 3x3 -> ReLU -> 2x2 max pool   (64,  8,  8)
    flatten (4096) -> dropout -> linear -> 6 scores (0-5 fingers)

Width = how many filters a layer has (16, 32, 64); depth = how many layers
(3 conv + 1 linear). Early filters find edges and skin/background color, later
ones combine them into finger-shaped parts, and each pool halves the image so
the next layer sees a bigger area. Trained with cross-entropy loss, because
the answer is a category, not a number.
"""

import cv2
import numpy as np
import torch
from torch import nn

import safe_config as cfg
import vision


class FingerNet(nn.Module):
    def __init__(self, classes=cfg.CLASSES):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 16, 5, padding=2)
        self.conv2 = nn.Conv2d(16, 32, 3, padding=1)
        self.conv3 = nn.Conv2d(32, 64, 3, padding=1)
        self.pool = nn.MaxPool2d(2)
        self.drop = nn.Dropout(0.3)
        self.fc = nn.Linear(64 * 8 * 8, classes)

    def forward(self, x):
        x = self.pool(torch.relu(self.conv1(x)))
        x = self.pool(torch.relu(self.conv2(x)))
        x = self.pool(torch.relu(self.conv3(x)))
        return self.fc(self.drop(x.flatten(1)))


def augment(crop, rng):
    """A new random version of a CROP x CROP training picture: turned,
    shifted, zoomed, maybe mirrored (a left hand), and with different
    lighting. Makes 1 picture worth many and helps with other people's hands."""
    size = vision.CROP
    angle = rng.uniform(-25, 25)
    scale = rng.uniform(0.85, 1.15)
    m = cv2.getRotationMatrix2D((size / 2, size / 2), angle, scale)
    m[:, 2] += rng.uniform(-0.12, 0.12, 2) * size
    img = cv2.warpAffine(crop, m, (size, size), borderMode=cv2.BORDER_REFLECT)
    if rng.random() < 0.5:
        img = img[:, ::-1]
    img = img.astype(np.float32)
    img = img * rng.uniform(0.7, 1.3) * rng.uniform(0.9, 1.1, 3) + rng.uniform(-25, 25)   # brightness, color cast
    if rng.random() < 0.3:
        img = cv2.GaussianBlur(img, (5, 5), rng.uniform(0.5, 1.5))
    img += rng.normal(0, 4, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def export_npz(net, path=cfg.NPZ_PATH):
    """The weights as plain numpy arrays, for numpy_net.py on the UNO Q."""
    np.savez(path, **{k: v.detach().cpu().numpy() for k, v in net.state_dict().items()})


def load(path=cfg.MODEL_PATH):
    saved = torch.load(path, weights_only=False)
    net = FingerNet()
    net.load_state_dict(saved["state"])
    return net.eval(), saved


@torch.no_grad()
def predict(net, crop):
    """CROP x CROP BGR picture -> 6 probabilities."""
    x = torch.from_numpy(vision.to_input(crop))[None]
    return torch.softmax(net(x), 1)[0].numpy()
