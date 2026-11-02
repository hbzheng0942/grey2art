import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync, renameSync, unlinkSync, openSync, closeSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';

export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
export const readJSON = path => JSON.parse(readFileSync(path, 'utf8'));
export function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
  return value;
}
export const fingerprint = value => sha256(JSON.stringify(canonical(value)));
export function writeJSON(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = path + '.' + randomUUID() + '.tmp';
  writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
  renameSync(temporary, path);
}
export function lock(path) {
  mkdirSync(dirname(path), { recursive: true });
  const fd = openSync(path, 'wx');
  writeFileSync(fd, JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }));
  closeSync(fd);
  return () => unlinkSync(path);
}
export function pngInfo(bytes) {
  if (bytes.length < 33 || !bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) || bytes.toString('ascii', 12, 16) !== 'IHDR') throw new Error('Not a PNG image');
  const width = bytes.readUInt32BE(16), height = bytes.readUInt32BE(20);
  if (!width || !height) throw new Error('Invalid PNG dimensions');
  return { width, height };
}
export function storeImage(root, source) {
  const bytes = readFileSync(source), dimensions = pngInfo(bytes), hash = sha256(bytes);
  const path = join(root, 'assets', 'sha256', hash + '.png');
  mkdirSync(dirname(path), { recursive: true });
  if (!existsSync(path)) writeFileSync(path, bytes, { flag: 'wx' });
  if (sha256(readFileSync(path)) !== hash) throw new Error('Canonical asset hash mismatch');
  return { path, sha256: hash, bytes: bytes.length, ...dimensions };
}
export function verifyArtifact(artifact) {
  if (!artifact?.path || !artifact.sha256) throw new Error('Missing artifact receipt');
  const bytes = readFileSync(artifact.path);
  if (sha256(bytes) !== artifact.sha256) throw new Error('Artifact changed; refusing paid regeneration');
  pngInfo(bytes);
}
