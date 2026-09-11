"""Associate device estimates with ASR item timestamps, never infer identity from text."""
from collections import deque

class SpeakerTimeline:
    def __init__(self):
        self.offset=0.0
        self.spans=deque()
    def append(self,byte_count,role):
        end=self.offset+byte_count/32  # 16 kHz, signed 16-bit mono: bytes/ms
        self.spans.append((self.offset,end,role))
        self.offset=end
        while self.spans and self.spans[0][1]<end-90000:
            self.spans.popleft()
    def role(self,start,end):
        if start is None or end is None or end<=start:
            return 'unknown'
        totals={'candidate':0.0,'interviewer':0.0,'unknown':0.0}
        for a,b,role in self.spans:
            overlap=max(0,min(b,end)-max(a,start))
            totals[role if role in totals else 'unknown']+=overlap
        duration=end-start
        for role in ('candidate','interviewer'):
            if totals[role]/duration>=0.8:
                return role
        return 'unknown'
