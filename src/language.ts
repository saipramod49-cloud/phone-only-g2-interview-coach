// Text containers cannot install a Telugu font. Keep phone text untouched and
// show a legible notice if unsupported Telugu script leaks into a lens frame.
export function lensSafeFrame(frame:string){
 if(!/[\u0c00-\u0c7f]/u.test(frame))return frame;
 return /(?:^|\n)ANSWER\b/.test(frame)
  ? 'LANGUAGE\n\nTelugu text is on your phone.\nChoose English or Romanized Telugu,\nthen Retry last answer.'
  : 'QUESTION\n\nTelugu question on phone.\nYour lens answer will use\nthe selected answer language.';
}
