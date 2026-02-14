---
language:
- en
license: apache-2.0
tags:
- vision-language
- image-text-to-text
- qwen3-vl
- sonia
pipeline_tag: image-text-to-text
library_name: transformers
base_model:
- medawgyt/Qwen3-VL-32B-Instruct
---

# Sonia-Qwen3-VL-32B

Sonia-Qwen3-VL-32B is a fine-tuned vision-language model derived from Qwen3-VL-32B-Instruct for assistant-style multimodal reasoning and response generation.

## Release identity

- Model ID: `medawgyt/Sonia-Qwen3-VL-32B`
- Release: `v1.0.0`
- Status: `ga`
- Shard layout: `14 safetensors shards`
- Packaging invariant: `model.safetensors.index.json` resolves to one contiguous shard family only.

## Training summary

- Base model: `medawgyt/Qwen3-VL-32B-Instruct`
- Fine-tune method: LoRA (merged)
- LoRA hyperparameters:
  - rank (r): `32`
  - alpha: `64`
  - dropout: `0.05`
- Precision: `bf16`
- Hardware: `2x A100 80GB`
- Steps / epochs: `984 / 2`
- Final train loss: `0.2146`
- Final eval loss: `0.1128`

## Intended use

- Multimodal assistant interaction (text + image)
- Vision-grounded instruction following
- Domain assistant behavior for Sonia workflows

## Out-of-scope use

- Safety-critical autonomous decisioning without human oversight
- High-risk medical, legal, or financial decision automation
- Identity/biometric inference from images without explicit governance

## Dataset provenance

1. SoniaDataset: curated multi-turn assistant conversations with persona anchoring
2. Inclusion policy: persona-consistent, instruction-following exchanges
3. Cleaning: deduplication, format normalization, persona anchor injection
4. Privacy: no PII in training data; synthetic conversations only
5. License: proprietary dataset, model weights Apache-2.0

## Evaluation

- Smoke test: 2-turn text inference on A100 (13.6 tok/s turn 1, 15.7 tok/s turn 2)
- Persona consistency: model identifies as Sonia across multi-turn exchanges
- Anchor preservation: training anchors (sonia-persona-dense) present in outputs
- Base model capabilities preserved (vision, instruction following)

## Quickstart (Transformers)

```python
import torch
from transformers import AutoModel, AutoProcessor

model_id = "medawgyt/Sonia-Qwen3-VL-32B"

processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
model = AutoModel.from_pretrained(
    model_id,
    torch_dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True,
)
model.eval()
print("Loaded:", model.__class__.__name__)
```

## Reproducibility contract

* Release manifest: `RELEASE_MANIFEST.json` with SHA-256 for weights/config/docs
* Artifact gate scripts:
   * `tools/release/verify_artifacts.py`
   * `tools/release/build_manifest.py`
   * `tools/release/smoke_load.py`
   * `tools/release/run_release_gate.py`
* Version pinning:
   * `transformers>=4.56.0`
   * `torch>=2.6.0`
   * `accelerate>=1.0.0`

## Limitations

* OCR edge cases
* Small text / low-contrast regions
* Multi-image context coherence limits
* Adversarial prompt sensitivity

## Citation

If you use this model, cite:

```bibtex
@misc{sonia_qwen3_vl_32b,
  title={Sonia-Qwen3-VL-32B},
  author={medawgyt},
  year={2026},
  publisher={Hugging Face},
  howpublished={\url{https://huggingface.co/medawgyt/Sonia-Qwen3-VL-32B}}
}
```
