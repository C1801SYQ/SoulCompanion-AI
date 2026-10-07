/** Public API origin validation without browser URL/DOM globals, also usable in native wx. */
export function safeCloudOrigin(value: string): boolean {
  if (value.length > 300) return false;
  const match = /^(https?):\/\/([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?\/?$/.exec(value);
  if (!match) return false;
  const [, protocol, hostname, port] = match;
  if (port && (Number(port) < 1 || Number(port) > 65535)) return false;
  if (hostname.length > 253 || hostname.split('.').some(label => !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label))) return false;
  return protocol === 'https' || ['127.0.0.1', 'localhost'].includes(hostname);
}
