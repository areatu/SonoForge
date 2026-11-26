"""Optional torch implementation of ML.3; importing this module never imports torch."""

from __future__ import annotations

import math

from echo_personal_tool.domain.services.echo_template_contract import (
    MAX_TEMPLATE_MODES,
    MAX_TEMPLATE_NODES,
    TEMPLATE_VIEWS,
)


def build_template_network(*, imagenet: bool = False):
    import torch
    from torch import nn
    from torch.nn import functional as f
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

    class EchoTemplateNetwork(nn.Module):
        """~2M parameters: MobileNetV3-Small + light FPN and coupled template heads."""

        def __init__(self):
            super().__init__()
            self.features = mobilenet_v3_small(
                weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1 if imagenet else None
            ).features
            self.lateral = nn.ModuleList([nn.Conv2d(c, 48, 1) for c in (24, 48, 576)])
            self.heatmaps = nn.Conv2d(48, 9, 1)
            self.visibility = nn.Linear(576, 9)
            self.embedding = nn.Linear(585, 128)
            self.prototypes = nn.Parameter(torch.randn(len(TEMPLATE_VIEWS), 128) * 0.02)
            self.logit_scale = nn.Parameter(torch.tensor(math.log(12.0)))
            self.pose = nn.Linear(576, len(TEMPLATE_VIEWS) * 5)
            self.coefficients = nn.Linear(576, len(TEMPLATE_VIEWS) * MAX_TEMPLATE_MODES)
            self.offsets = nn.Linear(576, len(TEMPLATE_VIEWS) * MAX_TEMPLATE_NODES)
            self.phase = nn.Linear(576, 2)
            nn.init.zeros_(self.pose.weight)
            with torch.no_grad():
                self.pose.bias.copy_(torch.tensor([0.0, 0.0, 1.0, 0.0, -5.5]).repeat(len(TEMPLATE_VIEWS)))

        def forward(self, image):
            maps = []
            feature = image
            for i, layer in enumerate(self.features):
                feature = layer(feature)
                if i in (3, 8, 12):
                    maps.append(feature)
            pyramid = self.lateral[2](maps[2])
            pyramid = f.interpolate(
                pyramid, size=maps[1].shape[-2:], mode="bilinear", align_corners=False
            ) + self.lateral[1](maps[1])
            pyramid = f.interpolate(
                pyramid, size=maps[0].shape[-2:], mode="bilinear", align_corners=False
            ) + self.lateral[0](maps[0])
            heatmaps = self.heatmaps(
                f.interpolate(
                    pyramid, size=(image.shape[-2] // 4, image.shape[-1] // 4), mode="bilinear", align_corners=False
                )
            )
            pooled = feature.mean(dim=(-2, -1))
            visibility = self.visibility(pooled)
            embedding = f.normalize(self.embedding(torch.cat([pooled, visibility.sigmoid()], dim=1)), dim=1)
            cosines = f.linear(embedding, f.normalize(self.prototypes, dim=1))
            logits = cosines * self.logit_scale.exp().clamp(1, 100)
            pose = self.pose(pooled).reshape(-1, len(TEMPLATE_VIEWS), 5)
            pose = torch.cat([pose[..., :2].sigmoid(), pose[..., 2:4], pose[..., 4:5].clamp(-8, 0)], dim=-1)
            coefficients = self.coefficients(pooled).reshape(-1, len(TEMPLATE_VIEWS), MAX_TEMPLATE_MODES).tanh() * 3
            offsets = self.offsets(pooled).reshape(-1, len(TEMPLATE_VIEWS), MAX_TEMPLATE_NODES).tanh() * 5
            return heatmaps, visibility, logits, cosines, pose, coefficients, offsets, self.phase(pooled)

    return EchoTemplateNetwork()
