# Local signing material

Private keys and Android keystores are not part of this source snapshot or its
history. The upstream firmware checkout contained keys under `app/keys/` and the
app checkout contained an Android keystore; these were deliberately excluded.

The firmware's existing sysbuild configuration refers to local files:

- `fw/app/keys/root-ec-p256.pem` for MCUboot signing.
- `fw/app/keys/nsib_priv.pem` for the network boot signing configuration.

Provide appropriate keys locally before attempting a complete signed build.
The entire `keys/` directory is ignored. Never commit keys to make a build work.
For an existing watch, an OTA image must use signing material accepted by its
installed bootloader. Generating a different key does not establish that
compatibility, and replacing the bootloader is not part of this project workflow.

The recorded local firmware build used the original workspace's signing
configuration. Its image signatures verified against that configured key, but
compatibility with the physical watch has not been tested.

For the Android app, `app/android/key.properties`, keystore files and CI signing
credentials stay local or in private CI secret storage. In their absence the
existing Gradle configuration signs release-mode local APKs with the Android
debug certificate. The research package ID is separate from the official app.
