/** Both OAuth and legacy SDK cache paths use this instance; no platform storage is touched. */
export class MemoryAuthStorage {
  private values = new Map<string, string>();
  getItemSync(key: string): string | null { return this.values.get(key) ?? null; }
  setItemSync(key: string, value: string): void { this.values.set(key, value); }
  removeItemSync(key: string): void { this.values.delete(key); }
  async getItem(key: string): Promise<string | null> { return this.getItemSync(key); }
  async setItem(key: string, value: string): Promise<void> { this.setItemSync(key, value); }
  async removeItem(key: string): Promise<void> { this.removeItemSync(key); }
  clear(): void { this.values.clear(); }
}
