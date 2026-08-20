export function devServerConfig(seatbeltSandbox: boolean) {
  return {
    watch: {
      ignored: ["**/.wrangler/**"],
      ...(seatbeltSandbox ? { useFsEvents: false, usePolling: true } : {}),
    },
  };
}
