#!/usr/bin/env python3
"""Smoke test: load Qwen3-VL model + processor, run tiny text-only generate."""
import argparse
import sys
import time
import torch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", default="VocaborSilentii/Qwen3-VL-32B-Instruct")
    ap.add_argument("--attn", default="flash_attention_2",
                     choices=["flash_attention_2", "sdpa", "eager"])
    args = ap.parse_args()

    print(f"Smoke test: {args.model_id}")
    print(f"  Attention: {args.attn}")
    print(f"  GPUs: {torch.cuda.device_count()}")
    print(f"  CUDA: {torch.cuda.is_available()}")
    print()

    t0 = time.time()

    # Load processor (includes tokenizer)
    from transformers import AutoProcessor
    print("Loading processor...")
    proc = AutoProcessor.from_pretrained(args.model_id, trust_remote_code=True)
    print(f"  Processor loaded ({time.time()-t0:.1f}s)")

    # Load model
    print("Loading model (bf16, device_map=auto)...")
    load_kwargs = dict(
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        low_cpu_mem_usage=True,
        use_safetensors=True,
        attn_implementation=args.attn,
    )

    model = None
    try:
        from transformers import AutoModelForImageTextToText
        model = AutoModelForImageTextToText.from_pretrained(args.model_id, **load_kwargs)
        print(f"  Loaded via AutoModelForImageTextToText")
    except Exception as e1:
        print(f"  AutoModelForImageTextToText failed: {e1}")
        try:
            from transformers import Qwen3VLForConditionalGeneration
            model = Qwen3VLForConditionalGeneration.from_pretrained(args.model_id, **load_kwargs)
            print(f"  Loaded via Qwen3VLForConditionalGeneration")
        except Exception as e2:
            print(f"  Qwen3VLForConditionalGeneration failed: {e2}")
            print("SMOKE FAILED: Could not load model")
            sys.exit(1)

    load_time = time.time() - t0
    print(f"  Model loaded in {load_time:.1f}s")
    print(f"  Model class: {type(model).__name__}")
    print(f"  Device map keys: {len(model.hf_device_map) if hasattr(model, 'hf_device_map') else 'N/A'}")

    # Tiny text-only generate
    print("\nRunning text-only generate...")
    messages = [{"role": "user", "content": [{"type": "text", "text": "Say hello in one word."}]}]
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = proc.tokenizer(text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=20)

    decoded = proc.tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    gen_time = time.time() - t0 - load_time
    print(f"  Generated: {decoded!r}")
    print(f"  Generate time: {gen_time:.1f}s")

    total = time.time() - t0
    print(f"\nSMOKE PASSED ({total:.1f}s total)")
    sys.exit(0)


if __name__ == "__main__":
    main()
