"""Optional ML.4 torch contracts (collection remains torch-free)."""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


def torch_runtime():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchvision")

    torch.set_num_threads(1)
    return torch


def test_ssl_import_and_help_do_not_require_torch(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    # The pure-core lane intentionally does not install the application. Its
    # conftest sys.path injection is not inherited by a fresh interpreter.
    # Replace inherited PYTHONPATH so this probe also works on an uninstalled
    # checkout rather than relying on a developer's editable installation.
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(root / "src"), str(root))))
    code = """
import builtins
real=builtins.__import__
def guarded(name,*a,**kw):
    if name.split('.')[0] in {'torch','torchvision','onnx','onnxruntime'}:
        raise AssertionError('eager optional ML dependency '+name)
    return real(name,*a,**kw)
builtins.__import__=guarded
import scripts.echo_ssl_losses
import scripts.echo_ssl_training
import scripts.train_self_supervised_echo as cli
try: cli.parse_args(['--help'])
except SystemExit as e: assert e.code == 0
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[2],
        env=os.environ.copy(),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "--manifest" in result.stdout and "--ema-decay" in result.stdout


def test_torch_physiology_parity_and_exactly_zero_low_confidence_gradients():
    torch = torch_runtime()
    from scripts.echo_ssl_losses import physiology_loss

    from echo_personal_tool.domain.services.echo_ssl_objectives import physiology_terms
    from tests.unit.test_echo_ssl_objectives import curves, field

    areas = {k: torch.tensor(v, dtype=torch.float64, requires_grad=True) for k, v in curves().items()}
    areas["LA"] = torch.tensor(100 - curves()["LA"], dtype=torch.float64, requires_grad=True)
    points = torch.zeros((24, 3, 2), dtype=torch.float64, requires_grad=True)
    with torch.no_grad():
        points[3] = 0.5
    pure = physiology_terms(
        {k: v.detach().numpy() for k, v in areas.items()}, field(), landmarks=points.detach().numpy()
    )
    result = sum(physiology_loss(areas, field(), landmarks=points).values())
    assert result.item() == pytest.approx(sum(pure.values()), rel=1e-10)
    result.backward()
    assert torch.isfinite(points.grad).all() and points.grad.abs().sum() > 0
    assert areas["LA"].grad.abs().sum() > 0
    low = {k: torch.full((24,), float("nan"), requires_grad=True) for k in areas}
    landmarks = torch.full((24, 3, 2), float("nan"), requires_grad=True)
    zero = sum(physiology_loss(low, field(0.599), landmarks=landmarks).values())
    assert zero.item() == 0
    zero.backward()
    assert all(torch.count_nonzero(x.grad) == 0 for x in [*low.values(), landmarks])
    # Empty chamber support retains a differentiable zero for valid graphs.
    assert sum(physiology_loss({}, field(), landmarks=points * 0).values()).item() == 0


def test_torch_warp_mask_ignores_invalid_targets_and_gradients():
    torch = torch_runtime()
    from scripts.echo_ssl_losses import warp_loss

    from echo_personal_tool.domain.services.echo_ssl_objectives import warp_consistency_loss

    pred = torch.tensor([[1.0, 2.0], [float("nan"), float("nan")]], requires_grad=True)
    targets = np.array([[4.0, 6.0], [np.nan, np.nan]])
    weights = np.array([0.8, 0.0])
    loss = warp_loss(pred, targets, weights)
    assert loss.item() == pytest.approx(warp_consistency_loss(pred.detach().numpy(), targets, weights))
    loss.backward()
    assert torch.isfinite(pred.grad).all() and torch.count_nonzero(pred.grad[1]) == 0


def test_continuous_mesh_decoding_and_ema_buffers():
    torch = torch_runtime()
    from scripts.echo_ssl_losses import update_ema
    from scripts.echo_template_losses import atlas_bank_arrays, decode_torch_mesh
    from scripts.echo_template_network import build_template_network

    from echo_personal_tool.domain.services.echo_template_contract import default_atlases

    bank = {k: torch.from_numpy(v) for k, v in atlas_bank_arrays(default_atlases()).items()}
    model = build_template_network().eval()
    with torch.no_grad():
        outputs = model(torch.zeros((3, 3, 64, 64)))
    weights = torch.tensor([0.0, 0.25, 1.0], requires_grad=True)
    result = decode_torch_mesh(
        outputs, torch.zeros(3, dtype=torch.long), torch.zeros(3, dtype=torch.long), bank, phase_weight=weights
    )
    torch.testing.assert_close(result[1], 0.75 * result[0] + 0.25 * result[2])
    result.square().sum().backward()
    assert torch.isfinite(weights.grad).all() and weights.grad.abs().sum() > 0
    discrete = decode_torch_mesh(outputs, torch.zeros(3, dtype=torch.long), torch.tensor([0, 0, 1]), bank)
    torch.testing.assert_close(result[[0, 2]], discrete[[0, 2]])
    student, teacher = torch.nn.BatchNorm1d(2), torch.nn.BatchNorm1d(2)
    with torch.no_grad():
        student.weight.fill_(4.0)
        student.running_mean.fill_(2.0)
        student.num_batches_tracked.fill_(7)
    update_ema(teacher, student, 0.75)
    torch.testing.assert_close(teacher.weight, torch.full((2,), 1.75))
    torch.testing.assert_close(teacher.running_mean, torch.full((2,), 0.5))
    assert teacher.num_batches_tracked.item() == 7
    with pytest.raises(ValueError):
        update_ema(teacher, student, 1.0)
