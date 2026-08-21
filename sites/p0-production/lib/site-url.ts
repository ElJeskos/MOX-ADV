function withHttps(raw: string) {
  const value = raw.trim();
  if (!value) throw new Error("Укажите публичный адрес сайта.");
  if (/^https?:\/\//iu.test(value)) {
    return value.replace(/^http:\/\//iu, "https://");
  }
  if (/^[a-z][a-z\d+.-]*:/iu.test(value)) {
    throw new Error("Поддерживается только публичный HTTPS-адрес.");
  }
  return `https://${value.replace(/^\/\//u, "")}`;
}

function parseIpv4(value: string) {
  const parts = value.split(".");
  if (parts.length !== 4 || parts.some((item) => !/^\d{1,3}$/u.test(item))) return null;
  const octets = parts.map(Number);
  return octets.every((item) => item >= 0 && item <= 255) ? octets : null;
}

export function isPublicIpAddress(raw: string): boolean {
  const value = raw.toLowerCase().replace(/^\[|\]$/gu, "").split("%", 1)[0];
  const ipv4 = parseIpv4(value);
  if (ipv4) {
    const [a, b, c] = ipv4;
    return !(
      a === 0
      || a === 10
      || a === 127
      || (a === 100 && b >= 64 && b <= 127)
      || (a === 169 && b === 254)
      || (a === 172 && b >= 16 && b <= 31)
      || (a === 192 && b === 0 && (c === 0 || c === 2))
      || (a === 192 && b === 168)
      || (a === 198 && (b === 18 || b === 19))
      || (a === 198 && b === 51 && c === 100)
      || (a === 203 && b === 0 && c === 113)
      || a >= 224
    );
  }
  if (!value.includes(":")) return true;
  if (value === "::" || value === "::1") return false;
  if (/^(?:fc|fd)/u.test(value) || /^fe[89ab]/u.test(value) || /^ff/u.test(value)) return false;
  if (/^2001:db8(?::|$)/u.test(value)) return false;
  const mapped = value.match(/(?:^|:)ffff:(.+)$/u)?.[1];
  if (!mapped) return true;
  if (mapped.includes(".")) return isPublicIpAddress(mapped);
  const groups = mapped.split(":").filter(Boolean);
  if (groups.length !== 2 || groups.some((item) => !/^[\da-f]{1,4}$/u.test(item))) return false;
  const high = Number.parseInt(groups[0], 16);
  const low = Number.parseInt(groups[1], 16);
  return isPublicIpAddress(`${high >> 8}.${high & 255}.${low >> 8}.${low & 255}`);
}

function validatePublicHttpsUrl(url: URL) {
  if (
    url.protocol !== "https:"
    || url.username
    || url.password
    || (url.port && url.port !== "443")
    || url.hash
  ) {
    throw new Error("Нужен публичный HTTPS-адрес без credentials, нестандартного порта и fragment.");
  }
  if ([...url.searchParams.keys()].some((key) => /^(?:access[_-]?token|oauth|api[_-]?key|auth|authorization|password|passwd|secret|signature|sig)$/iu.test(key))) {
    throw new Error("Credential-bearing URL запрещён.");
  }
  const host = url.hostname.toLowerCase();
  if (
    host === "localhost"
    || host.endsWith(".localhost")
    || host.endsWith(".local")
    || host.endsWith(".internal")
    || host.endsWith(".home.arpa")
    || !isPublicIpAddress(host)
  ) {
    throw new Error("Локальные и частные адреса, включая link-local, запрещены.");
  }
  return url;
}

export function normalizePublicHttpsUrl(raw: string) {
  return validatePublicHttpsUrl(new URL(withHttps(raw)));
}

export function requirePublicHttpsUrl(raw: string) {
  return validatePublicHttpsUrl(new URL(raw));
}
