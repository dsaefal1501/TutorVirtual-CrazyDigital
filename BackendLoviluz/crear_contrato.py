"""
backend/app/routers/crear_contrato.py
Endpoint para crear contratos en crazy_contratos con mapeo completo
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import logging

from app.services.dataverse import DataverseClient

logger = logging.getLogger(__name__)
router = APIRouter()

# ═══════════════════════════════════════════════════════════════
# MODELOS
# ═══════════════════════════════════════════════════════════════

class CrearContratoRequest(BaseModel):
    """Datos para crear un contrato completo en crazy_contratos"""
    
    # Campos básicos
    nombre: Optional[str] = Field(None, description="Nombre del contrato")
    cups: str = Field(..., min_length=18, max_length=25, description="CUPS del suministro")
    dni: Optional[str] = Field(None, description="DNI/CIF del cliente")
    
    # Relaciones (IDs de Dataverse)
    cliente_id: Optional[str] = Field(None, description="ID del cliente (contact)")
    comercializadora_id: Optional[str] = Field(None, description="ID de la comercializadora (account)")
    producto: Optional[str] = Field(None, description="Nombre del producto")
    comercial_id: Optional[str] = Field(None, description="ID del comercial (systemuser)")
    tarifa_id: Optional[str] = Field(None, description="ID de la tarifa")
    
    # Fechas
    fecha_firma: Optional[date] = Field(None, description="Fecha de firma")
    duracion_meses: int = Field(12, ge=1, le=48, description="Duración en meses")
    
    # Potencias P1-P6 (kW)
    potencia_p1: Optional[float] = Field(None, ge=0, description="Potencia P1 en kW")
    potencia_p2: Optional[float] = Field(None, ge=0, description="Potencia P2 en kW")
    potencia_p3: Optional[float] = Field(None, ge=0, description="Potencia P3 en kW")
    potencia_p4: Optional[float] = Field(None, ge=0, description="Potencia P4 en kW")
    potencia_p5: Optional[float] = Field(None, ge=0, description="Potencia P5 en kW")
    potencia_p6: Optional[float] = Field(None, ge=0, description="Potencia P6 en kW")
    
    # Fees Energía P1-P6 (€/kWh)
    fee_energia_p1: Optional[float] = Field(None, description="Fee energía P1")
    fee_energia_p2: Optional[float] = Field(None, description="Fee energía P2")
    fee_energia_p3: Optional[float] = Field(None, description="Fee energía P3")
    fee_energia_p4: Optional[float] = Field(None, description="Fee energía P4")
    fee_energia_p5: Optional[float] = Field(None, description="Fee energía P5")
    fee_energia_p6: Optional[float] = Field(None, description="Fee energía P6")
    
    # Fees Potencia P1-P6 (€/kW/día)
    fee_potencia_p1: Optional[float] = Field(None, description="Fee potencia P1")
    fee_potencia_p2: Optional[float] = Field(None, description="Fee potencia P2")
    fee_potencia_p3: Optional[float] = Field(None, description="Fee potencia P3")
    fee_potencia_p4: Optional[float] = Field(None, description="Fee potencia P4")
    fee_potencia_p5: Optional[float] = Field(None, description="Fee potencia P5")
    fee_potencia_p6: Optional[float] = Field(None, description="Fee potencia P6")
    
    # Comisiones
    comision_estimada: Optional[float] = Field(None, ge=0, description="Comisión estimada total")
    nivel_comision_comercial: Optional[float] = Field(None, description="% Comisión comercial")
    
    # Observaciones
    observaciones: Optional[str] = Field(None, description="Observaciones adicionales")

class CrearContratoResponse(BaseModel):
    """Respuesta al crear contrato"""
    status: str
    contrato_id: str
    mensaje: str
    cups: str
    fecha_creacion: datetime

# ═══════════════════════════════════════════════════════════════
# ENDPOINT: CREAR CONTRATO
# ═══════════════════════════════════════════════════════════════

@router.post("/contratos/crear", response_model=CrearContratoResponse)
async def crear_contrato(datos: CrearContratoRequest):
    """
    Crea un nuevo contrato en crazy_contratos con mapeo completo de campos
    """
    logger.info(f"📝 Creando contrato para CUPS: {datos.cups}")
    
    try:
        dv = DataverseClient()
        
        # ─────────────────────────────────────────────────────────
        # VALIDAR QUE NO EXISTA CONTRATO CON MISMO CUPS ACTIVO
        # ─────────────────────────────────────────────────────────
        contratos_existentes = dv.query(
            entity='crazy_contratos',
            filter_query=f"crazy_cups eq '{datos.cups}' and statecode eq 0",
            select_fields=['crazy_contratoid'],
            top=1
        )
        
        if contratos_existentes and len(contratos_existentes) > 0:
            raise HTTPException(
                400,
                f"Ya existe un contrato activo con CUPS {datos.cups}"
            )
        
        # ─────────────────────────────────────────────────────────
        # CONSTRUIR DATOS DEL CONTRATO
        # ─────────────────────────────────────────────────────────
        
        # Calcular fechas
        fecha_firma = datos.fecha_firma or date.today()
        fecha_vencimiento = fecha_firma + relativedelta(months=datos.duracion_meses)
        
        # Nombre del contrato
        nombre_contrato = datos.nombre or f"Contrato {datos.cups[:10]}"
        
        # Datos básicos
        data_contrato = {
            'crazy_nombre': nombre_contrato,
            'crazy_cups': datos.cups,
            'crazy_dni': datos.dni,
            'crazy_producto': datos.producto,
            'crazy_fechadefirma': fecha_firma.isoformat(),
            'crazy_fechavencimiento': fecha_vencimiento.isoformat(),
        }
        
        # Relaciones (Lookups con @odata.bind)
        if datos.cliente_id:
            data_contrato['crazy_cliente_contact@odata.bind'] = f"/contacts({datos.cliente_id})"
        
        if datos.comercializadora_id:
            data_contrato['crazy_comercializadora@odata.bind'] = f"/accounts({datos.comercializadora_id})"
        
        if datos.comercial_id:
            data_contrato['crazy_comercial@odata.bind'] = f"/systemusers({datos.comercial_id})"
        
        if datos.tarifa_id:
            data_contrato['crazy_tarifat@odata.bind'] = f"/products({datos.tarifa_id})"
        
        # Potencias P1-P6
        if datos.potencia_p1 is not None:
            data_contrato['crazy_potenciap1'] = datos.potencia_p1
        if datos.potencia_p2 is not None:
            data_contrato['crazy_potenciap2'] = datos.potencia_p2
        if datos.potencia_p3 is not None:
            data_contrato['crazy_potenciap3'] = datos.potencia_p3
        if datos.potencia_p4 is not None:
            data_contrato['crazy_potenciap4'] = datos.potencia_p4
        if datos.potencia_p5 is not None:
            data_contrato['crazy_potenciap5'] = datos.potencia_p5
        if datos.potencia_p6 is not None:
            data_contrato['crazy_potenciap6'] = datos.potencia_p6
        
        # Fees Energía P1-P6
        if datos.fee_energia_p1 is not None:
            data_contrato['crazy_feeenergiap1'] = datos.fee_energia_p1
        if datos.fee_energia_p2 is not None:
            data_contrato['crazy_feeenergiap2'] = datos.fee_energia_p2
        if datos.fee_energia_p3 is not None:
            data_contrato['crazy_feeenergiap3'] = datos.fee_energia_p3
        if datos.fee_energia_p4 is not None:
            data_contrato['crazy_feeenergiap4'] = datos.fee_energia_p4
        if datos.fee_energia_p5 is not None:
            data_contrato['crazy_feeenergiap5'] = datos.fee_energia_p5
        if datos.fee_energia_p6 is not None:
            data_contrato['crazy_feeenergiap6'] = datos.fee_energia_p6
        
        # Fees Potencia P1-P6
        if datos.fee_potencia_p1 is not None:
            data_contrato['crazy_feepotenciap1'] = datos.fee_potencia_p1
        if datos.fee_potencia_p2 is not None:
            data_contrato['crazy_feepotenciap2'] = datos.fee_potencia_p2
        if datos.fee_potencia_p3 is not None:
            data_contrato['crazy_feepotenciap3'] = datos.fee_potencia_p3
        if datos.fee_potencia_p4 is not None:
            data_contrato['crazy_feepotenciap4'] = datos.fee_potencia_p4
        if datos.fee_potencia_p5 is not None:
            data_contrato['crazy_feepotenciap5'] = datos.fee_potencia_p5
        if datos.fee_potencia_p6 is not None:
            data_contrato['crazy_feepotenciap6'] = datos.fee_potencia_p6
        
        # Comisiones
        if datos.comision_estimada is not None:
            data_contrato['crazy_comisionestimada'] = datos.comision_estimada
        if datos.nivel_comision_comercial is not None:
            data_contrato['crazy_nivelcomisioncomercial'] = datos.nivel_comision_comercial
        
        # Observaciones
        if datos.observaciones:
            data_contrato['crazy_observacionescomercial'] = datos.observaciones
        
        # ─────────────────────────────────────────────────────────
        # CREAR EN DATAVERSE
        # ─────────────────────────────────────────────────────────
        
        logger.info(f"📤 Enviando a Dataverse: {len(data_contrato)} campos")
        
        resultado = dv.create(
            entity='crazy_contratos',
            data=data_contrato
        )
        
        if not resultado or 'id' not in resultado:
            raise Exception("No se pudo crear el contrato en Dataverse")
        
        contrato_id = resultado['id']
        
        logger.info(f"✅ Contrato creado en Dataverse: {contrato_id}")
        
        return CrearContratoResponse(
            status='success',
            contrato_id=contrato_id,
            mensaje=f"Contrato creado exitosamente en crazy_contratos",
            cups=datos.cups,
            fecha_creacion=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creando contrato: {e}", exc_info=True)
        raise HTTPException(500, f"Error al crear contrato: {str(e)}")
