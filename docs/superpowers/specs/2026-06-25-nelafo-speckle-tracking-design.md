# NELAFO — Neural Lagrangian Flow Operator for Speckle Tracking Echocardiography

**Date:** 2026-06-25
**Status:** Draft (concept)
**Type:** Research / algorithm design
**Domain:** Echocardiography — myocardial strain (STE)

---

## 1. Executive Summary

NELAFO is a **qualitatively new approach** to myocardial speckle tracking that replaces
block-matching (NCC) and optical flow (LK/HS) with a **physics-constrained neural operator
trained by flow matching**. The myocardium is treated as a continuous hyperelastic body,
not a discrete set of speckle patterns. The method fuses multi-view B-mode + IQ signals
(A4C, A2C, A3C) into a unified continuous 3D Lagrangian displacement field, from which
the full Green–Lagrange strain tensor is obtained analytically. 

A generative (flow matching) formulation provides **per-voxel uncertainty estimates**,
addressing the key clinical weakness of current STE: unreliable regional strain.

---

## 2. Problem Statement

### 2.1 Clinical gap

Current speckle-tracking echocardiography (STE) achieves reproducible **global longitudinal
strain (GLS)** but suffers from high inter-observer variability for **regional (segmental)
strain**. The root causes are:

1. **Through-plane motion:** Speckles move out of the 2D imaging plane → decorrelation → lost tracks
2. **Block-matching rigidity:** The kernel assumes locally affine/persistent texture, which breaks under large rotation and deformation
3. **Post-hoc numerical differentiation:** Strain is computed via finite differences of noisy displacement → amplified noise
4. **No uncertainty quantification:** The clinician sees a single strain value without confidence bounds

### 2.2 Mathematical problem

Given:
- $\{I_v(x, t) \mid v \in \{\text{A4C}, \text{A2C}, \text{A3C}\}, t \in [0, T]\}$ — B-mode video for $N_{\text{views}}$ standard views over one cardiac cycle
- $\{Q_v(x, t)\}$ — corresponding IQ (quadrature) signal (complex-valued)
- $M_v(x)$ — LV segmentation mask at ED (end-diastole)

Find:
- Lagrangian displacement field $\phi_t(X): \Omega_0 \times [0,T] \to \mathbb{R}^3$ mapping each material point $X$ in the reference (ED) configuration to its deformed position $x = \phi_t(X)$
- Deformation gradient $F(X,t) = \nabla_X \phi_t(X)$
- Green–Lagrange strain $E(X,t) = \tfrac12(F^T F - I)$
- Per-voxel uncertainty $\sigma_E(X,t)$

---

## 3. Mathematical Formalism

### 3.1 Neural operator formulation

Let $\mathcal{A}$ be a Banach space of initial speckle fields (B-mode + IQ at ED)
and $\mathcal{U}$ a Banach space of displacement fields over $\Omega_0 \times [0,T]$.

We seek a **neural operator** $\mathcal{G}_\theta: \mathcal{A} \to \mathcal{U}$:

$$u = \mathcal{G}_\theta(a)$$

where $a = (I_{\text{ED}}, Q_{\text{ED}}, v, t)$ and $u(X,t) = \phi_t(X) - X$.

The operator $\mathcal{G}_\theta$ is parameterised as a **Fourier Neural Operator (FNO)**:

$$(\mathcal{K} v)(x) = \mathcal{F}^{-1}(R_\phi \cdot \mathcal{F} v)(x)$$

where $\mathcal{F}$ is the Fourier transform, $R_\phi$ is a learnable complex-valued weight
matrix in frequency space, and multiple Fourier layers are interleaved with pointwise
nonlinearities.

**Why FNO over INR (NeuralCMF):**
- FNO is resolution-agnostic: once trained, evaluate at any spatial/temporal query point
- Fourier domain naturally captures multi-scale deformation (low modes = global contraction, high modes = regional)
- Translation-equivariant by construction

### 3.2 Flow matching objective

We treat the deformation as a **conditional flow** on the space of displacement fields.
Define a time-dependent velocity field $v_t(X) = \partial_t \phi_t(X)$.

The flow matching objective is:

$$\mathcal{L}_{\text{FM}} = \mathbb{E}_{t \sim \mathcal{U}[0,1], a \sim p(a)} \left[ \left\| \mathcal{G}_\theta(a)(t) - v_t \right\|^2 \right]$$

but since the true $v_t$ is unknown, we use the **conditional flow matching** trick:
define a simple conditional probability path $p_t(u|u_1)$ that interpolates linearly
between $u_0 = 0$ and the target displacement $u_1$:

$$u_t = t \cdot u_1$$
$$v_t = u_1$$

The marginal objective is:

$$\mathcal{L}_{\text{CFM}} = \mathbb{E}_{t, a, u_1 \sim q(u_1|a)} \left[ \left\| \mathcal{G}_\theta(a)(t) - u_1 \right\|^2 \right]$$

where $q(u_1|a)$ is the conditional distribution of true displacement given the input field $a$.

### 3.3 Physics constraints

**Incompressibility** (myocardium is nearly incompressible, Poisson ratio $\nu \approx 0.49$):

$$\mathcal{L}_{\text{inc}} = \int_{\Omega_0} \|\nabla \cdot u(X,t)\|^2 \, dX \approx 0$$

**Positive Jacobian** (no fold-over):

$$\mathcal{L}_{\text{Jac}} = \int_{\Omega_0} \max(0, -\det(I + \nabla u))^2 \, dX$$

**Cycle consistency** (heart returns to ED configuration):

$$\mathcal{L}_{\text{cyc}} = \| \phi_T(X) - X \|^2$$

**Hyperelastic strain energy** (passive myocardium follows a constitutive law,
e.g. modified Mooney–Rivlin):

$$\mathcal{L}_{\text{mat}} = \int_{\Omega_0} \Psi_{\text{Mooney-Rivlin}}(C) \, dX$$

where $C = F^T F$ is the right Cauchy–Green tensor, and $\Psi$ penalises
physiologically implausible deformations.

### 3.4 Multi-view fusion

Each view $v$ sees a projection $P_v$ of the 3D displacement:

$$u_v(X) = P_v u(X)$$

The operator $\mathcal{G}_\theta$ maps **all views jointly** to a single 3D field,
with the consistency loss:

$$\mathcal{L}_{\text{view}} = \sum_v \int_{\text{FOV}_v} \| P_v \mathcal{G}_\theta(a) - u_v^{\text{obs}} \|^2$$

For single-view inference, the operator learns to complete the 3D field using
the incompressibility prior (the missing out-of-plane component is constrained
by $\nabla \cdot u = 0$).

### 3.5 Total loss

$$\mathcal{L}_{\text{total}} = \lambda_{\text{FM}} \mathcal{L}_{\text{CFM}} 
+ \lambda_{\text{inc}} \mathcal{L}_{\text{inc}} 
+ \lambda_{\text{Jac}} \mathcal{L}_{\text{Jac}} 
+ \lambda_{\text{cyc}} \mathcal{L}_{\text{cyc}} 
+ \lambda_{\text{mat}} \mathcal{L}_{\text{mat}} 
+ \lambda_{\text{view}} \mathcal{L}_{\text{view}}$$

---

## 4. Architecture

### 4.1 Overview

```
Input (ED frame for each view)
├── B-mode:    H×W×1  (log-compressed envelope)
├── IQ:        H×W×2  (real + imaginary)
├── Mask:      H×W×1  (LV segmentation at ED, optional)
├── View code: 1×N    (one-hot, N=3 for A4C/A2C/A3C)
└── Time t:    1 (normalised [0,1])
                │
                ▼
┌─────────────────────────────────────────────────────┐
│           Encoding Branch (per view)                 │
│   ┌─────┐   ┌────┐   ┌───────────┐   ┌──────────┐ │
│   │ CNN │──▶│FNO │──▶│ Temporal  │──▶│ Fourier  │ │
│   │enc  │   │2D  │   │ FNO (1D)  │   │ Mixer   │ │
│   └─────┘   └────┘   └───────────┘   └──────────┘ │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│         View Fusion (Cross-Attention)               │
│   Latent code from each view → common 3D latent     │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│       Decoding Branch (3D Fourier Neural Operator)   │
│   Maps: latent + query (X,Y,Z,t) → u(X,Y,Z,t)       │
│   Constraints: div(u)=0, det(I+∇u)>0 (projected)    │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│   Output                                             │
│   ├── u(X,t)         3D displacement                 │
│   ├── F(X,t)         Deformation gradient            │
│   ├── E(X,t)         Green-Lagrange strain           │
│   └── σ(E)(X,t)      Per-voxel uncertainty           │
└─────────────────────────────────────────────────────┘
```

### 4.2 Encoding branch (per-view)

Each view is processed independently before fusion:

1. **CNN encoder:** 4-layer residual CNN with downsampling
   - Input: [B-mode, I, Q, mask] = 4 channels
   - Output: feature grid F_v ∈ R^{H/4 × W/4 × D}

2. **2D Fourier layer:** capture multi-scale spatial correlations
   - 4 Fourier layers with GeLU activation
   - 16 frequency modes retained

3. **Temporal FNO (1D):** learn motion dynamics along cardiac cycle
   - Applied along t-axis after sampling multiple time points
   - 8 frequency modes

4. **Fourier Mixer:** cross-channel mixing in frequency space

### 4.3 View fusion (cross-attention)

Each view produces a latent $z_v \in \mathbb{R}^{N \times D}$.
These are fused via cross-attention:

$$z_{\text{fused}} = \text{CrossAttn}(Q=z_{\text{A4C}}, KV=[z_{\text{A2C}}, z_{\text{A3C}}])$$

A transformer with 4 heads and 2 layers.

For single-view inference: $z_{\text{fused}} = z_v$ (skip fusion).

### 4.4 Decoding branch (3D FNO)

The decoder is a **3D Fourier Neural Operator** that maps the fused latent
to the continuous displacement field:

Input: $z_{\text{fused}} \in \mathbb{R}^{D}$ — fused latent
Query: $(X, Y, Z, t) \in \mathbb{R}^4$ — continuous coordinates

Process:
1. Lift query to high-dim via positional encoding (sin/cos, 64 bands)
2. 6 Fourier layers (3D FNO) with residual connections
3. Project to $u \in \mathbb{R}^3$

**Hard incompressibility projection:**
After each Fourier layer, project the velocity field:

$$u \leftarrow u - \nabla (\Delta^{-1} (\nabla \cdot u))$$

via a learned Poisson solver (Helmholtz decomposition).
This enforces $\nabla \cdot u = 0$ as a **hard constraint**, not just a penalty.

### 4.5 Uncertainty head

A small MLP branch from the last Fourier layer outputs:
- $\log \sigma^2(u)$ — log-variance (heteroscedastic uncertainty)
- Trained with Gaussian negative log-likelihood loss

---

## 5. Training Strategy

### 5.1 Data requirements

| Source | Quantity | Usage |
|--------|----------|-------|
| Clinical echo cines (A4C/A2C/A3C) | ~500 studies | Unsupervised physics loss |
| Clinical echo + expert GLS | ~200 studies | Fine-tuning / validation |
| Synthetic (SIMUSAFE + Field II) | ~10,000 cycles | Pre-training (known ground truth) |

### 5.2 Curriculum

| Phase | Data | Loss | Epochs |
|-------|------|------|--------|
| 1. Pre-train | Synthetic videos with known $u$ | $\mathcal{L}_{\text{CFM}}$ only | 100 |
| 2. Physics warmup | Clinical, unsupervised | $\mathcal{L}_{\text{CFM}} + \mathcal{L}_{\text{inc}} + \mathcal{L}_{\text{Jac}} + \mathcal{L}_{\text{cyc}}$ | 200 |
| 3. Full physics | Clinical + synthetic | $\mathcal{L}_{\text{total}}$ (all terms) | 100 |
| 4. Fine-tune | Clinical + GLS labels | $\mathcal{L}_{\text{total}} + \lambda \| \text{GLS}_{\text{pred}} - \text{GLS}_{\text{expert}} \|^2$ | 50 |

### 5.3 Optimisation

| Parameter | Value |
|-----------|-------|
| Optimiser | AdamW |
| LR | 1e-4, cosine decay |
| Batch | 4 (limited by 3D FNO memory) |
| Gradient clipping | 1.0 |
| $\lambda_{\text{FM}}$ | 1.0 |
| $\lambda_{\text{inc}}$ | 0.1 |
| $\lambda_{\text{Jac}}$ | 0.01 |
| $\lambda_{\text{cyc}}$ | 0.05 |
| $\lambda_{\text{mat}}$ | 0.001 |
| $\lambda_{\text{view}}$ | 1.0 |

---

## 6. Inference

### 6.1 Clinical workflow

1. **Acquisition:** Standard 2D echo (any view or all 3)
2. **ED detection:** Auto-detect ED frame (largest LV volume / ECG gating)
3. **Segmentation:** Load pre-computed LV mask at ED (from existing pipeline)
4. **Run NELAFO:** Forward pass through operator → continuous 3D displacement
5. **Strain computation:** Analytical $E(X,t) = \tfrac12(F^T F - I)$ at any query point
6. **Bullseye plot:** Segment strain by AHA 17-segment model with uncertainty

### 6.2 Key outputs

| Output | Type | Notes |
|--------|------|-------|
| Longitudinal strain ($E_{ll}$) | Continuous field | AHA segments ±CI |
| Circumferential strain ($E_{cc}$) | Continuous field | From 3D reconstruction |
| Radial strain ($E_{rr}$) | Continuous field | From 3D reconstruction |
| GLS | Scalar ±CI | Global average |
| Strain rate | Field | $\dot{E} = dE/dt$ |
| Torsion | Scalar | Base-apex rotation difference |

---

## 7. Evaluation Plan

### 7.1 Metrics

| Metric | Purpose |
|--------|---------|
| GLS bias (Bland-Altman) vs expert | Clinical accuracy |
| GLS inter-observer variability | Reproducibility |
| Segment-level strain ICC | Regional accuracy (key improvement target) |
| Through-plane robustness metric | Synthetic data: known out-of-plane motion |
| Inference time | Clinical feasibility (< 30s) |
| Uncertainty calibration (ECE) | Reliability of $\sigma$ estimates |

### 7.2 Baselines

| Method | Notes |
|--------|-------|
| Clinical STE (Standard/AF GA) | Gold standard |
| NeuralCMF | INR-based, closest DL competitor |
| EchoTracker | Point-tracking-based |
| Block-matching (NCC, 31×31) | Classic baseline |

---

## 8. Limitations & Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| 3D FNO memory: O(N^3) scaling | Cannot handle full-volume | Factorised Fourier + patch-wise inference |
| Synthetic gap: sim-to-real | Model learns sim artifacts | Speckle decorrelation realignment (arXiv:2605.28697) |
| Multi-view misregistration | Out-of-plane fusion errors | Robust loss (Huber) + rigid registration pre-processing |
| Clinical compute: GPU required | Deployment on ultrasound scanners | Distillation to lightweight ONNX (post-training) |

---

## 9. Implementation Roadmap

| Phase | Effort | Deliverable |
|-------|--------|-------------|
| P0. Prototype (2D FNO, IQ only) | 2 weeks | Notebook: single-view 2D displacement |
| P1. Add flow matching + uncertainty | 2 weeks | Full 2D training with synthetic data |
| P2. Physics constraints | 1 week | div(u)=0 projection layer |
| P3. Multi-view fusion | 2 weeks | Cross-attention, 3→1 latent |
| P4. 3D FNO decoder | 2 weeks | Continuous 3D field output |
| P5. Clinical validation | 2 weeks | Retrospective study |
| P6. ONNX export + integration | 2 weeks | Integration into existing echo pipeline |

---

## 10. Related Work

| Work | Year | Relation |
|------|------|----------|
| NeuralCMF (Shen et al., TMI 2024) | 2024 | INR for 3D cardiac motion; closest prior art |
| EchoTracker (Azad et al., ICCV 2025) | 2025 | Point tracking adapted for echo |
| Sim2Real STE (Judge et al., 2026) | 2026 | Photorealistic synthetic data pipeline |
| FNO (Li et al., ICLR 2021) | 2021 | Fourier neural operator foundation |
| Flow Matching (Lipman et al., ICML 2023) | 2023 | Generative framework for continuous normalising flows |
| OSA (Wang et al., 2026) | 2026 | Stiefel manifold for temporal consistency in echo |
