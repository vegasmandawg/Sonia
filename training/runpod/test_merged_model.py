#!/usr/bin/env python3
"""
Smoke test: load base model from local HF cache + apply LoRA adapter.
Avoids re-downloading 67GB merged model (disk quota workaround).
"""
import os, sys, time, torch

HF_TOKEN = os.environ.get("HF_TOKEN", "")
BASE_MODEL = "VocaborSilentii/Qwen3-VL-32B-Instruct"
ADAPTER_DIR = "/workspace/output/sonia-lora"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def main():
    log("=" * 60)
    log("SMOKE TEST: base + LoRA adapter (local)")
    log("=" * 60)

    log(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            name = torch.cuda.get_device_name(i)
            mem = torch.cuda.get_device_properties(i).total_memory / 1e9
            log(f"  GPU {i}: {name} ({mem:.1f} GB)")

    # Load processor
    log("Loading processor...")
    t0 = time.time()
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(BASE_MODEL, token=HF_TOKEN, trust_remote_code=True)
    log(f"Processor loaded ({time.time()-t0:.1f}s)")

    # Load base model
    log("Loading base model (bf16, auto device map)...")
    t0 = time.time()
    from transformers import AutoModelForImageTextToText
    model = AutoModelForImageTextToText.from_pretrained(
        BASE_MODEL,
        token=HF_TOKEN,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    load_time = time.time() - t0
    log(f"Base model loaded ({load_time:.1f}s)")

    # Apply LoRA adapter
    log(f"Applying LoRA adapter from {ADAPTER_DIR}...")
    t0 = time.time()
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    model = model.merge_and_unload()
    merge_time = time.time() - t0
    log(f"LoRA merged in-memory ({merge_time:.1f}s)")

    if hasattr(model, 'hf_device_map'):
        devices = set(str(v) for v in model.hf_device_map.values())
        log(f"  Device map spans: {devices}")

    # Run inference
    log("Running inference...")
    messages = [
        {"role": "system", "content": "You are Sonia, a warm and intelligent AI companion."},
        {"role": "user", "content": "Hello Sonia! Tell me something interesting about yourself in one sentence."},
    ]

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], return_tensors="pt").to(model.device)

    t0 = time.time()
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=128,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
        )

    gen_time = time.time() - t0
    new_tokens = output_ids[0][inputs["input_ids"].shape[1]:]
    response = processor.decode(new_tokens, skip_special_tokens=True)
    num_tokens = len(new_tokens)

    log(f"Generation complete ({gen_time:.1f}s, {num_tokens} tokens, {num_tokens/gen_time:.1f} tok/s)")
    log(f"")
    log(f"RESPONSE: {response}")
    log(f"")

    # Second prompt - multi-turn
    log("Running second prompt (multi-turn)...")
    messages.append({"role": "assistant", "content": response})
    messages.append({"role": "user", "content": "What can you help me with today?"})

    text2 = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs2 = processor(text=[text2], return_tensors="pt").to(model.device)

    t0 = time.time()
    with torch.no_grad():
        output_ids2 = model.generate(
            **inputs2,
            max_new_tokens=200,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
        )

    gen_time2 = time.time() - t0
    new_tokens2 = output_ids2[0][inputs2["input_ids"].shape[1]:]
    response2 = processor.decode(new_tokens2, skip_special_tokens=True)
    num_tokens2 = len(new_tokens2)

    log(f"Generation complete ({gen_time2:.1f}s, {num_tokens2} tokens, {num_tokens2/gen_time2:.1f} tok/s)")
    log(f"")
    log(f"RESPONSE 2: {response2}")
    log(f"")

    # Summary
    log("=" * 60)
    log("SMOKE TEST PASSED")
    log(f"  Base: {BASE_MODEL}")
    log(f"  Adapter: {ADAPTER_DIR}")
    log(f"  Load time: {load_time:.1f}s (base) + {merge_time:.1f}s (merge)")
    log(f"  Turn 1: {gen_time:.1f}s ({num_tokens} tokens, {num_tokens/gen_time:.1f} tok/s)")
    log(f"  Turn 2: {gen_time2:.1f}s ({num_tokens2} tokens, {num_tokens2/gen_time2:.1f} tok/s)")
    log("=" * 60)

if __name__ == "__main__":
    main()
