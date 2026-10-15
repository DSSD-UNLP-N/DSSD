from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..db import get_db
from ..models import Inventario, Compromiso, CompromisoItem, EstadoCompromiso, Ong
from ..schemas import CompromisoIn, CompromisoOut, LiberacionOut

router = APIRouter(prefix="/adjudicaciones", tags=["Adjudicaciones y Bloqueos"])

@router.post("/bloquear", response_model=CompromisoOut)
def bloquear_recursos(payload: CompromisoIn, db: Session = Depends(get_db)):
    # 1. Validar que la ONG exista y esté habilitada
    ong = db.query(Ong).filter(Ong.id == payload.ong_id).first()
    if not ong or ong.estado.name != "HABILITADA":
        raise HTTPException(status_code=400, detail="ONG inexistente o no habilitada")

    # Idempotencia: Si ya existe el compromiso, lo devolvemos sin hacer nada
    compromiso_existente = db.query(Compromiso).filter(
        Compromiso.emergencia_id == payload.emergencia_id,
        Compromiso.ong_id == payload.ong_id,
        Compromiso.estado == EstadoCompromiso.ACTIVO
    ).first()
    
    if compromiso_existente:
        return compromiso_existente
    
    recurso_ids = [item.tipo_recurso_id for item in payload.items]
    
    try:
        # 2. LOCKING TRANSACCIONAL ORDENADO: Previene Deadlocks
        inventarios = (
            db.query(Inventario)
            .filter(
                Inventario.ong_id == payload.ong_id,
                Inventario.tipo_recurso_id.in_(recurso_ids)
            )
            .order_by(Inventario.tipo_recurso_id)
            .with_for_update()
            .all()
        )
        
        inventario_map = {inv.tipo_recurso_id: inv for inv in inventarios}
        
        # 3. Validar stock
        for req_item in payload.items:
            inv = inventario_map.get(req_item.tipo_recurso_id)
            if not inv:
                raise HTTPException(status_code=404, detail=f"Recurso {req_item.tipo_recurso_id} no encontrado en la ONG.")
                
            disponible = inv.cantidad_total - inv.cantidad_comprometida
            if req_item.cantidad > disponible:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, 
                    detail=f"Stock insuficiente para recurso {req_item.tipo_recurso_id}. Disponible: {disponible}"
                )
            
            inv.cantidad_comprometida += req_item.cantidad

        # 4. Registrar Compromiso
        nuevo_compromiso = Compromiso(
            emergencia_id=payload.emergencia_id,
            ong_id=payload.ong_id,
            estado=EstadoCompromiso.ACTIVO
        )
        db.add(nuevo_compromiso)
        db.flush() 
        
        for req_item in payload.items:
            db.add(CompromisoItem(
                compromiso_id=nuevo_compromiso.id,
                tipo_recurso_id=req_item.tipo_recurso_id,
                cantidad=req_item.cantidad
            ))

        db.commit()
        db.refresh(nuevo_compromiso)
        return nuevo_compromiso

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicto: Ya existe un compromiso para esta emergencia y ONG, o hay recursos duplicados en la petición.")
    except Exception:
        db.rollback()
        raise

@router.post("/{compromiso_id}/liberar", response_model=LiberacionOut)
def liberar_recursos(compromiso_id: int, db: Session = Depends(get_db)):
    try:
        compromiso = (
            db.query(Compromiso)
            .filter(Compromiso.id == compromiso_id)
            .with_for_update()
            .first()
        )
        
        if not compromiso:
            raise HTTPException(status_code=404, detail="Compromiso no encontrado")
            
        if compromiso.estado == EstadoCompromiso.LIBERADO:
            return LiberacionOut(compromiso_id=compromiso.id, estado=compromiso.estado, mensaje="Los recursos ya estaban liberados")
            
        recurso_ids = [item.tipo_recurso_id for item in compromiso.items]
        inventarios = (
            db.query(Inventario)
            .filter(
                Inventario.ong_id == compromiso.ong_id,
                Inventario.tipo_recurso_id.in_(recurso_ids)
            )
            .order_by(Inventario.tipo_recurso_id)
            .with_for_update()
            .all()
        )
        
        inventario_map = {inv.tipo_recurso_id: inv for inv in inventarios}
        
        for item in compromiso.items:
            inv = inventario_map.get(item.tipo_recurso_id)
            if not inv:
                raise HTTPException(status_code=500, detail=f"Inconsistencia crítica: Inventario faltante para recurso {item.tipo_recurso_id}")
            if inv.cantidad_comprometida < item.cantidad:
                raise HTTPException(status_code=500, detail="Inconsistencia crítica: La cantidad a liberar es mayor que la comprometida actualmente")
                
            inv.cantidad_comprometida -= item.cantidad
                
        compromiso.estado = EstadoCompromiso.LIBERADO
        db.commit()
        
        return LiberacionOut(compromiso_id=compromiso.id, estado=compromiso.estado, mensaje="Recursos liberados exitosamente")
        
    except Exception:
        db.rollback()
        raise