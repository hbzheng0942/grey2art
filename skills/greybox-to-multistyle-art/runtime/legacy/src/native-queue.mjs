import { randomUUID } from 'node:crypto';
import { nativeCallOverlap } from './metrics.mjs';
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { validateBatch } from './image-batch.mjs';
import { prepareImageManifest } from './art-direction.mjs';
import { readJSON, writeJSON, fingerprint, lock, storeImage, verifyArtifact } from './storage.mjs';

export class NativeQueue {
  constructor(root, runId) {
    if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(runId || '')) throw new Error('Invalid run id');
    this.root = root; this.dir = join(root, 'runs', runId);
  }
  atomic(fn) {
    mkdirSync(this.dir, { recursive: true });
    const release = lock(join(this.dir, '.lock'));
    try { return fn(); } finally { release(); }
  }
  prepare(manifest) {
    if(manifest.stage==='asset-reference'&&!manifest.assetContext?.realization&&!existsSync(join(this.dir,'manifest.json')))
      throw new Error('New asset production requires executable realization constraints; legacy manifests are resume-only');
    if(manifest.stage==='art-repair-reference'&&manifest.compilerRevision!==2&&!existsSync(join(this.dir,'manifest.json')))
      throw new Error('Legacy repair compiler is resume-only; compile from current targets');
    manifest = prepareImageManifest(manifest, this.root);
    validateBatch(manifest);
    return this.atomic(() => {
      const path = join(this.dir, 'manifest.json'), identity = fingerprint(manifest);
      if (existsSync(path)) {
        if (readJSON(path).identity !== identity) throw new Error('Frozen native batch changed');
      } else writeJSON(path, { identity, manifest, createdAt: Date.now(), route: 'host-direct' });
      for (const task of manifest.tasks) {
        const path = this.taskFile(task.id);
        if (!existsSync(path)) writeJSON(path, { id: task.id, requestHash: fingerprint(task), status: 'pending' });
      }
      return { identity, tasks: manifest.tasks.length, concurrency: manifest.concurrency };
    });
  }
  taskFile(id) {
    if (!/^[a-z0-9][a-z0-9-]{0,79}$/.test(id || '')) throw new Error('Invalid task id');
    return join(this.dir, 'tasks', id + '.json');
  }
  records() {
    return readJSON(join(this.dir, 'manifest.json')).manifest.tasks.map(task => ({ task, record: readJSON(this.taskFile(task.id)) }));
  }
  claim() {
    return this.atomic(() => {
      const { manifest } = readJSON(join(this.dir, 'manifest.json'));
      const records = this.records();
      for (const { record } of records) if (record.status === 'succeeded') verifyArtifact(record.artifact);
      const occupied = records.filter(({ record }) => !['pending', 'succeeded'].includes(record.status)).length;
      const available = Math.max(0, manifest.concurrency - occupied);
      return records.filter(({ record }) => record.status === 'pending').slice(0, available).map(({ task, record }) => {
        for (const input of task.images || []) verifyArtifact(input);
        const lease = { ...record, status: 'running', leaseId: randomUUID(), claimedAt: Date.now() };
        writeJSON(this.taskFile(task.id), lease);
        const toolArguments = { prompt: task.prompt, transparent_background: false, ...(task.images?.length ? { referenced_image_paths: task.images.map(i => i.path) } : {}) };
        return { ...task, toolArguments, leaseId: lease.leaseId, requestHash: lease.requestHash, claimedAt: lease.claimedAt };
      });
    });
  }
  complete(receipt) {
    return this.atomic(() => {
      const path = this.taskFile(receipt.id), record = readJSON(path);
      if (record.leaseId !== receipt.leaseId || record.requestHash !== receipt.requestHash) throw new Error('Receipt does not match leased request');
      const task = this.records().find(r => r.task.id === receipt.id).task;
      if (task.images?.length) {
        for (const input of task.images) verifyArtifact(input);
        const expected = { prompt: task.prompt, transparent_background: false, referenced_image_paths: task.images.map(i => i.path) };
        if (!receipt.invocationArguments || fingerprint(receipt.invocationArguments) !== fingerprint(expected)) throw new Error('Reference-image invocation arguments must match the leased request');
      }
      if (!['running','succeeded'].includes(record.status)) throw new Error('Task is not leased');
      if (receipt.tool !== 'image_gen.imagegen' || typeof receipt.sourcePath !== 'string' || !receipt.outputHint?.includes(receipt.sourcePath)) throw new Error('Tool-reported source path required');
      if (!Number.isFinite(receipt.startedAt) || !Number.isFinite(receipt.finishedAt) || receipt.finishedAt < receipt.startedAt || receipt.startedAt < record.claimedAt) throw new Error('Invalid tool timing');
      const artifact = storeImage(this.root, receipt.sourcePath);
      if (record.status === 'succeeded' && record.artifact.sha256 !== artifact.sha256) throw new Error('Cannot replace a completed output');
      const result = { ...record, ...receipt, artifact, status: 'succeeded', elapsedMs: receipt.finishedAt - receipt.startedAt, cost: { imageMoney: null }, visualAcceptance: 'pending' };
      writeJSON(path, result);
      return result;
    });
  }
  summary() {
    const records = this.records().map(r => r.record), finished = records.filter(r => r.status === 'succeeded');
    const complete = finished.length === records.length;
    const callOverlap = nativeCallOverlap(finished);
    const concurrency = readJSON(join(this.dir,'manifest.json')).manifest.concurrency;
    const throughputWarning = complete && finished.length >= 6 && concurrency === 2 && callOverlap.averageInFlight < 1.4 ? 'Low observed overlap: concurrency configuration alone does not establish sustained parallel execution' : null;
    return { callOverlap, throughputWarning, route: 'host-direct', total: records.length, succeeded: finished.length, status: complete ? 'completed' : 'incomplete', elapsedMs: complete ? Math.max(...finished.map(r => r.finishedAt)) - Math.min(...finished.map(r => r.startedAt)) : null, tasks: records, imageMoney: null, visualAcceptance: 'pending' };
  }
}
