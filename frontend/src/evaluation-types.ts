export interface EvaluationDataset {id:string;name:string;description:string;createdAt:string;total:number;good:number;bad:number;}
export interface CaseAnnotations {label:'goodcase'|'badcase';reviewStatus:'pending'|'reviewed';tags:string[];note:string;expectedAnswer:string;}
export interface EvaluationCase extends CaseAnnotations {id:string;datasetId:string;sourceKind:'run'|'log';sourceId:string;runId?:string;appId:string;appName:string;sourceStatus:string;sourceCreatedAt:string;input:unknown;output:unknown;createdAt:string;updatedAt:string;archived:boolean;snapshot?:Record<string,unknown>;}
export interface CaseSource {sourceKind:'run'|'log';sourceId:string;}
export const emptyAnnotations:CaseAnnotations={label:'badcase',reviewStatus:'pending',tags:[],note:'',expectedAnswer:''};
export const caseText=(v:unknown)=>v===null||v===undefined?'未采集':typeof v==='string'?v:JSON.stringify(v,null,2);

export const caseQuestion=(v:unknown)=>v&&typeof v==='object'&&'question' in v?caseText((v as Record<string,unknown>).question):caseText(v);
