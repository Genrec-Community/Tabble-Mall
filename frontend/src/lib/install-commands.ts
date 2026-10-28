/** Builds the one-line install commands shown (once) after pairing a print agent. */

// The same whitelist the installers enforce, so a command mangled in a chat message is refused
// before it touches anything. The server only ever produces these characters.
const URL_OK = /^https?:\/\/[A-Za-z0-9.:\-_/]+$/;
const TOKEN_OK = /^[A-Za-z0-9._\-]+$/;

export interface InstallCommands {
  windows: string;
  linux: string;
}

export function installCommands(origin: string, token: string): InstallCommands | null {
  const url = origin.replace(/\/+$/, "");
  if (!URL_OK.test(url) || !TOKEN_OK.test(token)) return null;
  return {
    windows: `powershell -ExecutionPolicy Bypass -File install.ps1 -Url ${url} -Token ${token}`,
    linux: `sudo bash install.sh --url ${url} --token ${token}`,
  };
}
