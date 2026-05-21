import json
import re

# Read the recruiter.json file
with open(r'c:\Users\Srikanth Tata\Downloads\hiring\static\recruiter.json', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the target pink color (from admin.json)
pink_color = [0.9652, 0.9148, 0.94, 1]

# Define color patterns to replace (from the file analysis)
# These are the main colors found in recruiter.json
color_patterns = [
    # Blue color
    (r'\[\s*0\.448188632142\s*,\s*0\.546735456878\s*,\s*0\.755046051624\s*,\s*1\s*\]', 
     '[0.9652, 0.9148, 0.94, 1]'),
    # Green color
    (r'\[\s*0\.642359595205\s*,\s*0\.836661364985\s*,\s*0\.520584585152\s*,\s*1\s*\]',
     '[0.9652, 0.9148, 0.94, 1]'),
    # Orange color
    (r'\[\s*0\.907620837642\s*,\s*0\.532730940277\s*,\s*0\.260757565966\s*,\s*1\s*\]',
     '[0.9652, 0.9148, 0.94, 1]'),
]

# Apply replacements
for pattern, replacement in color_patterns:
    content = re.sub(pattern, replacement, content)

# Write back to file
with open(r'c:\Users\Srikanth Tata\Downloads\hiring\static\recruiter.json', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully updated recruiter.json colors to violet/pink theme")
