"""Modelos del modulo de proveedores, planes y afiliaciones de seguro."""

from pydantic import BaseModel, Field


class InsuranceContribution(BaseModel):
    type: str = "percentage"  # percentage | fixed_amount | remainder
    value: str | None = "0"


class InsuranceProvider(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    status: str = "active"
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""


class InsurancePlan(BaseModel):
    id: str = ""
    providerId: str = ""
    name: str = ""
    description: str = ""
    status: str = "active"
    billingFrequency: str = "monthly"
    currency: str = "DOP"
    baseAmount: str = "0"
    companyContribution: InsuranceContribution = Field(default_factory=InsuranceContribution)
    employeeContribution: InsuranceContribution = Field(default_factory=InsuranceContribution)
    payrollConceptId: str = "SEGURO"
    prorationPolicy: str = "none"
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""


class InsuranceEnrollment(BaseModel):
    id: str = ""
    employeeId: str = ""
    dependentId: str = ""
    contractId: str = ""
    providerId: str = ""
    planId: str = ""
    coverageType: str = "primary"
    startDate: str = ""
    endDate: str = ""
    status: str = "active"
    baseAmount: str = "0"
    currency: str = "DOP"
    companyContributionType: str = "percentage"
    companyContributionValue: str | None = "0"
    companyContributionAmount: str = "0"
    employeeContributionType: str = "percentage"
    employeeContributionValue: str | None = "0"
    employeeContributionAmount: str = "0"
    payrollConceptId: str = "SEGURO"
    prorationPolicy: str = "none"
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""
    cancelledBy: str = ""
    cancelledAt: str = ""
