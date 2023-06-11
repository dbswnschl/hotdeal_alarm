import os

try:
    import cloudscraper
except:
    os.system("pip install --upgrade cloudscraper")
try:
    import pywebpush
except:
    os.system("pip install --upgrade pywebpush")