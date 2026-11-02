import { existsSync, appendFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fingerprint, readJSON, writeJSON, lock, verifyArtifact } from './storage.mjs';
import { validateArtBatch } from './art-direction.mjs';

export function validateBatch(manifest) {
  if (manifest) validateArtBatch(manifest);
  if (!manifest || !Array.isArray(manifest.tasks) || !manifest.tasks.length) throw new Error('Empty batch');
  if (!Number.isInteger(manifest.concurrency) || manifest.concurrency < 1 || manifest.concurrency > 4) throw new Error('Concurrency must be 1..4');
  if (!Number.isInteger(manifest.maxCalls) || manifest.maxCalls < manifest.tasks.length) throw new Error('Call envelope must cover the batch');
  const ids = new Set();
  for (const task of manifest.tasks) {
    if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(task.id) || ids.has(task.id)) throw new Error('Invalid or duplicate task id');
    if (typeof task.prompt !== 'string' || !task.prompt.trim()) throw new Error('Missing prompt');
    if (task.images && (!Array.isArray(task.images) || task.images.some(i => !i.path || !/^[a-f0-9]{64}$/.test(i.sha256)))) throw new Error('Images require path and SHA256');
    ids.add(task.id);
  }
}

// One durable file per task: no shared mutable whole-plan writes.
export async function runBatch({ manifest, runDir, generate, onEvent = () => {} }) {
  validateBatch(manifest);
  mkdirSync(runDir, { recursive: true });
  const unlock = lock(join(runDir, '.lock'));
  try {
    const identity = fingerprint(manifest), manifestFile = join(runDir, 'manifest.json');
    if (existsSync(manifestFile) && readJSON(manifestFile).identity !== identity) throw new Error('Frozen batch changed; use a new run id');
    if (!existsSync(manifestFile)) writeJSON(manifestFile, { identity, manifest, createdAt: new Date().toISOString() });
    const records = manifest.tasks.map(task => {
      const path = join(runDir, 'tasks', task.id + '.json');
      const record = existsSync(path) ? readJSON(path) : { id: task.id, status: 'pending' };
      if (record.status === 'succeeded') verifyArtifact(record.artifact);
      return { task, path, record };
    });
    const unresolved = records.filter(r => !['succeeded', 'pending'].includes(r.record.status));
    if (unresolved.length) throw new Error('Reconciliation required before new calls: ' + unresolved.map(r => r.task.id).join(', '));
    const summaryFile = join(runDir, 'summary.json');
    if (records.every(r => r.record.status === 'succeeded') && existsSync(summaryFile)) return { ...readJSON(summaryFile), resumedWithoutCalls: true };
    const startedAt = Date.now(), pending = records.filter(r => r.record.status === 'pending');
    let cursor = 0, active = 0, peak = 0, calls = 0, stopped = false;
    const emit = event => {
      const value = { at: Date.now(), ...event };
      appendFileSync(join(runDir, 'events.jsonl'), JSON.stringify(value) + '\n');
      onEvent(value);
    };
    const worker = async workerIndex => {
      while (!stopped && cursor < pending.length) {
        const entry = pending[cursor++];
        const { task, path } = entry;
        if (++calls > manifest.maxCalls) throw new Error('Call envelope exhausted');
        active++; peak = Math.max(peak, active);
        const taskStart = Date.now();
        entry.record = { id: task.id, history: entry.record.history || [], status: 'running', requestHash: fingerprint(task), startedAt: taskStart, workerIndex, cost: { imageMoney: null }, visualAcceptance: 'pending' };
        writeJSON(path, entry.record);
        emit({ type: 'started', taskId: task.id, active });
        try {
          const result = await generate(task, {
            workerIndex,
            onProgress: metadata => { entry.record.metadata = metadata; writeJSON(path, entry.record); },
            onToolEvent: event => emit({ ...event, taskId: task.id })
          });
          verifyArtifact(result.artifact);
          entry.record = { ...entry.record, ...result, status: 'succeeded', finishedAt: Date.now(), elapsedMs: Date.now() - taskStart };
        } catch (error) {
          // Never reinterpret an uncertain submitted request as a retryable failure.
          stopped = true;
          entry.record = { ...entry.record, status: error.definitelyNotSubmitted ? 'failed' : 'unknown', error: error.message, finishedAt: Date.now(), elapsedMs: Date.now() - taskStart, metadata: error.callMetadata || entry.record.metadata || null };
        }
        writeJSON(path, entry.record);
        active--;
        emit({ type: entry.record.status, taskId: task.id, active, elapsedMs: entry.record.elapsedMs });
      }
    };
    const workers = await Promise.allSettled(Array.from({ length: Math.min(manifest.concurrency, pending.length) }, (_, i) => worker(i)));
    const fatal = workers.find(r => r.status === 'rejected');
    if (fatal) throw fatal.reason;
    const summary = {
      schema: 1, identity, startedAt, finishedAt: Date.now(), elapsedMs: Date.now() - startedAt,
      requestedConcurrency: manifest.concurrency, peakTaskConcurrency: peak,
      scheduledCalls: calls, reusedSuccesses: records.length - pending.length,
      succeeded: records.filter(r => r.record.status === 'succeeded').length, total: records.length,
      status: records.every(r => r.record.status === 'succeeded') ? 'completed' : 'needs-reconciliation',
      imageMoney: null, visualAcceptance: 'pending',
      recoveredAfterFailure: records.some(r => r.record.history?.length > 0),
      totalTaskElapsedMs: records.reduce((sum, r) => sum + (r.record.elapsedMs || 0), 0),
      priorFailedAttempts: records.flatMap(r => (r.record.history || []).map(h => ({ id: r.task.id, elapsedMs: h.elapsedMs, error: h.error, reconciliation: h.reconciliation }))),
      tasks: records.map(r => ({ id: r.task.id, status: r.record.status, elapsedMs: r.record.elapsedMs ?? null, artifact: r.record.artifact ?? null, usage: r.record.usage ?? null, toolEvents: r.record.toolEvents ?? [] }))
    };
    writeJSON(summaryFile, summary);
    return summary;
  } finally { unlock(); }
}
