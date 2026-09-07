# Project Collaboration Rules

## Runtime Environment

- The service runs in Docker on `192.168.1.1`, with container name `gemini-srt-translator-bazarr` and web port `6789`.
- SSH command: `ssh root@192.168.1.1`. Run SSH connections to the device outside the sandbox, subject to the current tool permission settings.
- Service data directory on the host: `/opt/docker/gemini-srt-translator-bazarr`.
- Queue directory on the host: `/opt/docker/bazarr/postprocess/queue`, mapped to `/queue` in the container.
- Bazarr enqueue script: `/opt/docker/bazarr/postprocess/gst_enqueue.sh`.

## Build and Deployment

- Images are built through GitHub. The default scope is to modify repository code, run relevant tests, and report results; do not build images locally or on the remote device.
- Use read-only SSH checks when the live service state is needed. A code change request does not authorize deployment. Modify container files, replace remote scripts, or restart or recreate containers only when the user explicitly requests an update to the running service.
- Deploy using images built through GitHub. If the user explicitly requests a temporary direct container modification, back up the affected files first and explain that a normal restart preserves the changes, while recreating the container from an image overwrites changes made inside the container.
- Clearly distinguish repository code changes, completed GitHub image builds, and running container updates in reports. Claim only states that have been verified.
