# test_huggingface.py
# ----------------------------------------------------
# Standalone tester for Hugging Face text generation
# using moonshotai/Kimi-K2-Thinking
#
# Run: python test_huggingface.py
# ----------------------------------------------------

import traceback

print("\n🔍 Testing Hugging Face: moonshotai/Kimi-K2-Thinking\n")

try:
    from transformers import pipeline
except Exception as e:
    print("❌ transformers not installed:", e)
    print("Run: pip install transformers sentencepiece")
    exit(1)

MODEL = "moonshotai/Kimi-K2-Thinking"

try:
    print("⏳ Loading model on CPU (no accelerate, no device_map)…")
    pipe = pipeline(
        "text-generation",
        model=MODEL,
        trust_remote_code=True,   # needed for this model
        # NOTE: no device_map="auto" here, so accelerate is not required
    )
    print("✅ Model loaded!")
except Exception:
    print("❌ Failed to load model:")
    traceback.print_exc()
    exit(1)

prompt = "Explain the importance of data quality in one short sentence."

print("\n🧪 Generating text…\n")
try:
    # Some custom models expect a "messages" format, others plain text.
    # We try both, in order.
    out = None

    try:
        # 1) Chat-style call
        print("→ Trying message-style input…")
        out = pipe(
            [{"role": "user", "content": prompt}],
            max_new_tokens=80,
        )
        print("\n✅ Message-style output:")
        print(out)
    except Exception:
        # 2) Fallback: plain text
        print("→ Message-style failed, trying plain text…")
        out = pipe(prompt, max_new_tokens=80)
        print("\n✅ Plain text output:")
        print(out)

    print("\n🎉 HF test completed successfully!")
except Exception:
    print("\n❌ Error during generation:")
    traceback.print_exc()
