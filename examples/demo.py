"""Safe documentation demo: synthetic data only, no production services or network."""
import sys, tempfile, json, os, subprocess
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bot
b=object.__new__(bot.Bot)
report={'checked_at':'<current UTC time>','services':{'web-demo':{'ok':True},'backup-demo':{'ok':False}}}
with patch.object(b,'health',return_value=(report,['backup-demo'])):print(b.status())
print()
print(bot.format_gpu({'gpu':96.2,'gpu_engines':{'rcs0':8.1,'vcs0':96.2,'bcs0':0.4}}))
# No token, Telegram API call or message delivery is used in this demo.
