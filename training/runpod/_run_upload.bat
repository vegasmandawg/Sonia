@echo off
set HF_TOKEN=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
cd /d S:\training\runpod
echo Starting upload...
S:\envs\sonia-core\python.exe upload_to_hf.py > S:\training\runpod\_upload_output.txt 2>&1
echo Exit code: %ERRORLEVEL%
type S:\training\runpod\_upload_output.txt
