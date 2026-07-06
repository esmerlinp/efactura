"""
Event Bus híbrido: in-process (desarrollo) + Redis Pub/Sub (producción).

El bus permite publicar eventos de dominio y suscribir handlers.
Los handlers se ejecutan de forma asíncrona (en un thread) para no
bloquear la operación principal.

Parte del Plan de Evolución ERP - Fase 1.2: Event Bus.
"""

import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from app.events.events import DomainEvent, event_from_json

logger = logging.getLogger(__name__)

# Tipo de handler: recibe un DomainEvent y no retorna nada
EventHandler = Callable[[DomainEvent], None]


class EventBus:
    """Bus de eventos con soporte dual in-process / Redis.

    Modo in-process (default):
        Los handlers se ejecutan en hilos separados dentro del mismo proceso.
        Ideal para desarrollo y despliegues pequeños.

    Modo Redis:
        Publica eventos en canales Redis Pub/Sub.
        Handlers se ejecutan en workers separados que se suscriben a los canales.
        Ideal para producción multi-proceso.
    """

    # Canal base para Redis Pub/Sub
    CHANNEL_PREFIX = "vykone:events"

    def __init__(self, redis_client=None):
        """Inicializa el bus de eventos.

        Args:
            redis_client: Cliente redis.Redis opcional. Si es None, usa modo in-process.
        """
        self._redis = redis_client
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._subscribed_channels: Set[str] = set()
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False

    # ── Public API ──────────────────────────────────────────────────

    def publish(self, event: DomainEvent) -> None:
        """Publica un evento de dominio.

        En modo in-process: ejecuta todos los handlers suscritos en hilos.
        En modo Redis: publica en el canal correspondiente.

        Args:
            event: El evento de dominio a publicar.
        """
        if self._redis:
            self._publish_redis(event)
        else:
            self._publish_in_process(event)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Suscribe un handler a un tipo de evento.

        Args:
            event_type: Nombre de la clase del evento (ej. 'InvoiceEmitted').
            handler: Función callback que recibe el DomainEvent.
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug("Handler registrado para evento '%s': %s", event_type, handler.__name__)

    def start_listener(self) -> None:
        """Inicia el listener de Redis en un hilo separado (solo modo Redis).

        Escucha todos los canales suscritos y despacha eventos a los handlers.
        """
        if not self._redis:
            logger.warning("start_listener llamado sin Redis configurado. Ignorando.")
            return
        if self._running:
            return
        self._running = True
        self._listener_thread = threading.Thread(
            target=self._listen_redis,
            daemon=True,
            name="event-bus-listener",
        )
        self._listener_thread.start()
        logger.info("Event Bus Listener iniciado (Redis Pub/Sub)")

    def stop_listener(self) -> None:
        """Detiene el listener de Redis."""
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
        logger.info("Event Bus Listener detenido")

    # ── In-Process Implementation ───────────────────────────────────

    def _publish_in_process(self, event: DomainEvent) -> None:
        """Ejecuta handlers suscritos en hilos separados."""
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            return
        for handler in handlers:
            thread = threading.Thread(
                target=self._execute_handler,
                args=(handler, event),
                daemon=True,
                name=f"evt-{event.event_type}",
            )
            thread.start()

    @staticmethod
    def _execute_handler(handler: EventHandler, event: DomainEvent) -> None:
        """Ejecuta un handler capturando excepciones."""
        try:
            handler(event)
        except Exception:
            logger.exception(
                "Error en handler '%s' para evento %s",
                handler.__name__,
                event.event_type,
            )

    # ── Redis Implementation ───────────────────────────────────────

    def _channel_name(self, event_type: str) -> str:
        """Retorna el nombre del canal Redis para un tipo de evento."""
        return f"{self.CHANNEL_PREFIX}:{event_type}"

    def _publish_redis(self, event: DomainEvent) -> None:
        """Publica el evento en Redis Pub/Sub."""
        channel = self._channel_name(event.event_type)
        message = event.to_json()
        try:
            self._redis.publish(channel, message)
            logger.debug("Evento publicado en Redis canal '%s'", channel)
        except Exception:
            logger.exception("Error al publicar evento en Redis canal '%s'", channel)
            # Fallback: ejecutar handlers in-process si Redis falla
            self._publish_in_process(event)

    def _listen_redis(self) -> None:
        """Loop principal del listener de Redis."""
        if not self._redis:
            return
        pubsub = self._redis.pubsub()

        # Suscribirse a todos los canales con handlers registrados
        channels = [self._channel_name(et) for et in self._handlers]
        if channels:
            pubsub.subscribe(*channels)
            logger.info("Suscrito a canales Redis: %s", channels)

        try:
            while self._running:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    self._handle_redis_message(message)
        except Exception:
            logger.exception("Error en listener Redis")
        finally:
            pubsub.close()

    def _handle_redis_message(self, message: Dict[str, Any]) -> None:
        """Procesa un mensaje recibido de Redis."""
        try:
            channel: str = message.get("channel", "")
            data_str: str = message.get("data", "{}")
            event = event_from_json(data_str)
            handlers = self._handlers.get(event.event_type, [])
            for handler in handlers:
                self._execute_handler(handler, event)
        except Exception:
            logger.exception("Error al procesar mensaje de Redis")


# Instancia global del bus de eventos (singleton)
_bus_instance: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Retorna la instancia global del EventBus.

    Si no se ha inicializado, crea una instancia en modo in-process.
    """
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = EventBus()
    return _bus_instance


def init_event_bus(redis_client=None) -> EventBus:
    """Inicializa (o reinicializa) el EventBus global.

    Args:
        redis_client: Cliente redis.Redis opcional para modo producción.

    Returns:
        La instancia del EventBus.
    """
    global _bus_instance
    _bus_instance = EventBus(redis_client=redis_client)
    return _bus_instance
