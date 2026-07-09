import os

ui_path = "app/ui.py"
with open(ui_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace login page logo branding style
old_branding = """            <div style="
                display:inline-flex;align-items:center;justify-content:center;
                width:70px;height:70px;background:linear-gradient(135deg,#4F46E5,#7C3AED);
                border-radius:20px;box-shadow:0 8px 24px rgba(79,70,229,0.4);
                margin-bottom:18px;font-size:32px;
            ">🛡️</div>"""

new_branding = """            <div style="
                display:inline-flex;align-items:center;justify-content:center;
                width:70px;height:70px;background:linear-gradient(135deg,var(--primary),var(--secondary));
                border-radius:20px;box-shadow:0 8px 24px var(--accent-glow);
                margin-bottom:18px;font-size:32px;
            ">🛡️</div>"""

if old_branding in content:
    content = content.replace(old_branding, new_branding)
    print("Patched login logo branding successfully.")
else:
    print("Warning: old_branding not found")

with open(ui_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patch complete.")
