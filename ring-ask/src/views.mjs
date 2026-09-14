export function answerVariants(text) {
  const clean = String(text || '').trim();
  const result = {flow:'', spoken:'', explain:'', keywords:''};
  const headers = [...clean.matchAll(/(?:^|\n)(FLOW|SPOKEN|EXPLAIN|KEYWORDS):\s*/gi)];
  for (let index=0; index<headers.length; index++) {
    const match=headers[index], key=match[1].toLowerCase();
    const start=(match.index||0)+match[0].length;
    const end=index+1<headers.length ? headers[index+1].index : clean.length;
    result[key]=clean.slice(start,end).trim();
  }
  if (!headers.length) result.spoken=clean;
  return result;
}

function rows(text) {
  return String(text || '').split('\n').map(line=>line.trim().replace(/^->\s*/, '')).filter(Boolean);
}

function labelled(line) {
  const parts=line.split(/\s+[—–-]\s+/,2);
  return {label:(parts[0]||'').trim().toUpperCase(), text:(parts[1]||parts[0]||'').trim()};
}

export function pairedViews(flow, explain) {
  const explanations=rows(explain).map(labelled);
  return rows(flow).map((line,index)=>{
    const item=labelled(line);
    const match=explanations.find(value=>value.label===item.label)||explanations[index];
    return {flow:line, explanation:match?.text||item.text};
  });
}
