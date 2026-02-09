# Bootstrap Runbook

1. Run folder architecture script.
2. Run `Initialize-SoniaPhase2.ps1`.
3. Fill env placeholders securely.
4. Run diagnostics:
   - `powershell -ExecutionPolicy Bypass -File S:\scripts\diagnostics\doctor.ps1`
5. Start services:
   - `powershell -ExecutionPolicy Bypass -File S:\scripts\ops\start-all.ps1`
