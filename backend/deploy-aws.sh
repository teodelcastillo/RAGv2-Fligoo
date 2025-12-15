#!/bin/bash

# Script de Despliegue Automatizado para AWS
# Uso: ./deploy-aws.sh [--skip-build] [--skip-migrations]

set -e  # Salir si hay algún error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Funciones de utilidad
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}→ $1${NC}"
}

# Verificar que estamos en el directorio correcto
if [ ! -f "docker-compose-prod.yml" ]; then
    print_error "No se encontró docker-compose-prod.yml. Asegúrate de estar en el directorio backend/"
    exit 1
fi

# Verificar que existe el archivo .env
if [ ! -f "docker/.env" ]; then
    print_error "No se encontró docker/.env. Cópialo desde docker/template.env y configúralo."
    exit 1
fi

print_info "Iniciando despliegue en AWS..."

# Verificar Git (opcional)
if command -v git &> /dev/null; then
    print_info "Verificando estado de Git..."
    if [ -n "$(git status --porcelain)" ]; then
        print_error "Hay cambios sin commitear. Considera hacer commit antes de desplegar."
        read -p "¿Continuar de todas formas? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    CURRENT_BRANCH=$(git branch --show-current)
    print_info "Rama actual: $CURRENT_BRANCH"
fi

# Detener contenedores existentes
print_info "Deteniendo contenedores existentes..."
docker-compose -f docker-compose-prod.yml down || true

# Construir imagen (a menos que se pase --skip-build)
if [[ ! "$*" == *"--skip-build"* ]]; then
    print_info "Construyendo imagen Docker..."
    docker build -f docker/Dockerfile -t backend:latest .
    print_success "Imagen construida correctamente"
else
    print_info "Saltando construcción de imagen (--skip-build)"
fi

# Iniciar servicios
print_info "Iniciando servicios..."
docker-compose -f docker-compose-prod.yml up -d
print_success "Servicios iniciados"

# Esperar a que los servicios estén listos
print_info "Esperando a que los servicios estén listos..."
sleep 10

# Verificar que los contenedores están corriendo
print_info "Verificando estado de contenedores..."
if ! docker-compose -f docker-compose-prod.yml ps | grep -q "Up"; then
    print_error "Algunos contenedores no están corriendo. Revisa los logs:"
    docker-compose -f docker-compose-prod.yml logs
    exit 1
fi
print_success "Todos los contenedores están corriendo"

# Ejecutar migraciones (a menos que se pase --skip-migrations)
if [[ ! "$*" == *"--skip-migrations"* ]]; then
    print_info "Ejecutando migraciones de base de datos..."
    docker-compose -f docker-compose-prod.yml exec -T backend python manage.py migrate
    print_success "Migraciones aplicadas"
else
    print_info "Saltando migraciones (--skip-migrations)"
fi

# Recolectar archivos estáticos
print_info "Recolectando archivos estáticos..."
docker-compose -f docker-compose-prod.yml exec -T backend python manage.py collectstatic --noinput
print_success "Archivos estáticos recolectados"

# Verificar salud de la aplicación
print_info "Verificando salud de la aplicación..."
sleep 5
if curl -f http://localhost/api/ > /dev/null 2>&1; then
    print_success "La API está respondiendo correctamente"
else
    print_error "La API no está respondiendo. Revisa los logs:"
    docker-compose -f docker-compose-prod.yml logs backend
fi

# Verificar Celery worker
print_info "Verificando Celery worker..."
if docker-compose -f docker-compose-prod.yml exec -T celery-worker celery -A main inspect ping > /dev/null 2>&1; then
    print_success "Celery worker está funcionando"
else
    print_error "Celery worker no responde. Revisa los logs:"
    docker-compose -f docker-compose-prod.yml logs celery-worker
fi

# Mostrar estado final
echo ""
print_success "Despliegue completado!"
echo ""
print_info "Estado de los contenedores:"
docker-compose -f docker-compose-prod.yml ps
echo ""
print_info "Para ver los logs: docker-compose -f docker-compose-prod.yml logs -f"
print_info "Para ver logs de un servicio específico: docker-compose -f docker-compose-prod.yml logs -f [backend|celery-worker|nginx]"

