from pydantic import BaseModel,Field
class CorrectionItem(BaseModel):
    sample_code:str=Field(min_length=1,max_length=80)
    reference_value:float|None=Field(default=None,ge=0,le=100,allow_inf_nan=False)
    candidate_value:float|None=Field(default=None,ge=0,le=100,allow_inf_nan=False)
class RevisionInput(BaseModel):
    base_version:int=Field(ge=1)
    reason:str=Field(min_length=5,max_length=600)
    corrections:list[CorrectionItem]=Field(min_length=1,max_length=5000)
