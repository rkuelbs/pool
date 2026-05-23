# poolctl systemd deployment

1. Copy repo to `/opt/poolctl` on the Pi and create the venv.
2. Install unit:
   - `sudo cp deploy/systemd/poolctl.service /etc/systemd/system/poolctl.service`
3. Reload and enable:
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable --now poolctl.service`
4. Check status/logs:
   - `sudo systemctl status poolctl.service`
   - `journalctl -u poolctl.service -f`

Health endpoint:
- `http://<pi-ip>:8000/api/health`
