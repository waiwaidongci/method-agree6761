import {request,post} from './client';
import type {Dataset,RevisionPreview,RevisionConfirm,RevisionTrail} from '../types/domain';
export const getDatasets=()=>request<Dataset[]>('/datasets');
export const createDataset=(data:unknown)=>post<{id:number;row_count:number}>('/datasets',data);
export interface CorrectionInput{sample_code:string;reference_value:number|null;candidate_value:number|null}
export interface RevisionPayload{base_version:number;reason:string;corrections:CorrectionInput[]}
export const previewRevision=(datasetId:number,payload:RevisionPayload)=>post<RevisionPreview>(`/datasets/${datasetId}/revisions/preview`,payload);
export const confirmRevision=(datasetId:number,payload:RevisionPayload)=>post<RevisionConfirm>(`/datasets/${datasetId}/revisions/confirm`,payload);
export const getRevisions=(datasetId:number)=>request<RevisionTrail[]>(`/datasets/${datasetId}/revisions`);
