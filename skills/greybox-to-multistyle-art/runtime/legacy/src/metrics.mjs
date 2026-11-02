export function imageOverlap(tasks) {
  const intervals = [];
  for (const task of tasks) {
    const starts = new Map();
    for (const event of task.toolEvents || []) {
      if (event.type === 'image-started') starts.set(event.itemId, event.at);
      if (event.type === 'image-completed' && starts.has(event.itemId)) intervals.push({ taskId: task.id, startedAt: starts.get(event.itemId), finishedAt: event.at });
    }
  }
  if (!intervals.length) return { observedIntervals: 0, peak: null, overlapMs: null, intervals };
  const events = intervals.flatMap(i => [[i.startedAt, 1], [i.finishedAt, -1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let active = 0, peak = 0, overlapMs = 0, previous = events[0][0];
  for (const [at, delta] of events) {
    if (active > 1) overlapMs += at - previous;
    active += delta; peak = Math.max(peak, active); previous = at;
  }
  return { observedIntervals: intervals.length, peak, overlapMs, intervals };
}

// Native host receipts measure client call overlap, not provider execution time.
export function nativeCallOverlap(records) {
  const intervals = records.filter(r => Number.isFinite(r.startedAt) && Number.isFinite(r.finishedAt));
  if (!intervals.length) return { observedIntervals: 0, averageInFlight: null, peak: null, overlapMs: null };
  const overlap = imageOverlap(intervals.map(r => ({ id:r.id, toolEvents:[{type:'image-started',itemId:r.id,at:r.startedAt},{type:'image-completed',itemId:r.id,at:r.finishedAt}] })));
  const wallMs = Math.max(...intervals.map(r=>r.finishedAt))-Math.min(...intervals.map(r=>r.startedAt));
  const callMs = intervals.reduce((n,r)=>n+r.finishedAt-r.startedAt,0);
  return { observedIntervals:intervals.length, wallMs, callMs, averageInFlight:wallMs>0?callMs/wallMs:null, peak:overlap.peak, overlapMs:overlap.overlapMs };
}
