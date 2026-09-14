export function answerVariants(text) {
  const clean = String(text || '').trim();
  const result = {flow:'', spoken:'', keywords:''};
  const headers = [...clean.matchAll(/(?:^|\n)(FLOW|SPOKEN|KEYWORDS):\s*/gi)];
  for (let index=0; index<headers.length; index++) {
    const match=headers[index], key=match[1].toLowerCase();
    const start=(match.index||0)+match[0].length;
    const end=index+1<headers.length ? headers[index+1].index : clean.length;
    result[key]=clean.slice(start,end).trim();
  }
  if (!headers.length) result.flow=clean;
  return result;
}
