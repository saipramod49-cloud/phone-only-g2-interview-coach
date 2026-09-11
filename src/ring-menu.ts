export const ringActions = [
 ['listen', 'Listen / next question'], ['finish', 'Finish question'],
 ['pause', 'Pause microphone'], ['retry', 'Retry last answer'],
 ['reconnect', 'Reconnect + listen'], ['back', 'Back to answer'],
] as const;
export class RingMenu {
 open=false; index=0;
 move(direction:number){this.index=(this.index+direction+ringActions.length)%ringActions.length;}
 tap(){if(!this.open){this.open=true;this.index=0;return null;}const action=ringActions[this.index][0];this.open=false;return action;}
 back(){if(!this.open)return false;this.open=false;return true;}
 frame(){return 'ACTIONS\n\n'+ringActions.map((a,i)=>(i===this.index?'> ':'  ')+a[1]).join('\n');}
}
