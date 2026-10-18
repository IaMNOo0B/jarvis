import ollama

def chat_with_local_model(model_name, prompt):
    try:
        response = ollama.chat(model=model_name, messages=[
            {
                'role': 'user',
                'content': prompt,
            },
        ])
        return response['message']['content']
    except Exception as e:
        return f"Error: {e}"

# testing with visual-identified model
print(chat_with_local_model('hf.co/ge525/Qwen3.8B-Distill-uncensored-heretic-Q4_K_M-GGUF:Q4_K_M', 'Hello!'))
