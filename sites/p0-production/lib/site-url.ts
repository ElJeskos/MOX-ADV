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
  const host = url.hostname.toLowerCase();
  if (
    host === "localhost"
    || host.endsWith(".local")
    || /^(127\.|10\.|192\.168\.|169\.254\.|0\.|::1$)/u.test(host)
    || /^172\.(1[6-9]|2\d|3[01])\./u.test(host)
  ) {
    throw new Error("Локальные и частные адреса запрещены.");
  }
  return url;
}

export function normalizePublicHttpsUrl(raw: string) {
  return validatePublicHttpsUrl(new URL(withHttps(raw)));
}

export function requirePublicHttpsUrl(raw: string) {
  return validatePublicHttpsUrl(new URL(raw));
}
