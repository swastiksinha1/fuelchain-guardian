# Production Deployment Guide

## Prerequisites

- AWS account with EKS access (or GKE / DigitalOcean Kubernetes)
- `kubectl` configured
- `helm` 3.x installed
- Docker images pushed to a registry (GHCR or ECR)

---

## 1. Create EKS Cluster

```bash
# Install eksctl
brew install eksctl

# Create cluster (2 x m5.xlarge nodes — 4 vCPU, 16 GB each)
eksctl create cluster \
  --name fuelchain-prod \
  --region ap-south-1 \
  --nodegroup-name standard \
  --node-type m5.xlarge \
  --nodes 3 \
  --nodes-min 2 \
  --nodes-max 8 \
  --managed

# Update kubeconfig
aws eks update-kubeconfig --name fuelchain-prod --region ap-south-1
```

---

## 2. Install Cluster Add-ons

```bash
# NGINX Ingress Controller
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.replicaCount=2

# cert-manager for TLS
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true

# Create ClusterIssuer for Let's Encrypt
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: rishi@fuelchain.dev
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
EOF
```

---

## 3. Create Secrets

```bash
# Create namespace first
kubectl apply -f k8s/namespace.yaml

# Create secrets (fill in real values)
kubectl create secret generic fuelchain-secrets \
  --namespace fuelchain \
  --from-literal=DATABASE_URL='postgresql+asyncpg://fuelchain:STRONG_PASS@postgres:5432/fuelchain' \
  --from-literal=REDIS_URL='redis://redis:6379/0' \
  --from-literal=JWT_SECRET='$(openssl rand -hex 32)' \
  --from-literal=AISHUB_API_KEY='your_aishub_key' \
  --from-literal=TWITTER_BEARER_TOKEN='your_twitter_token' \
  --from-literal=RAZORPAY_KEY_ID='your_razorpay_key' \
  --from-literal=RAZORPAY_KEY_SECRET='your_razorpay_secret' \
  --from-literal=POSTGRES_PASSWORD='STRONG_PASS'

# Store Firebase service account
kubectl create secret generic firebase-credentials \
  --namespace fuelchain \
  --from-file=service-account.json=./secrets/firebase-service-account.json
```

---

## 4. Deploy Infrastructure

```bash
# Deploy Postgres, Redis, Redpanda
kubectl apply -f k8s/infra.yaml

# Wait for Postgres to be ready
kubectl wait --for=condition=ready pod -l app=postgres \
  -n fuelchain --timeout=120s

# Run migrations (one-off Job)
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  namespace: fuelchain
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: ghcr.io/YOUR_ORG/fuelchain-backend:latest
        command: ["alembic", "upgrade", "head"]
        envFrom:
        - configMapRef:
            name: fuelchain-config
        - secretRef:
            name: fuelchain-secrets
EOF

kubectl wait --for=condition=complete job/db-migrate -n fuelchain --timeout=60s

# Initialize Kafka topics
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: init-kafka
  namespace: fuelchain
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: init
        image: ghcr.io/YOUR_ORG/fuelchain-backend:latest
        command: ["python", "-m", "scripts.init_kafka"]
        envFrom:
        - configMapRef:
            name: fuelchain-config
        - secretRef:
            name: fuelchain-secrets
EOF
```

---

## 5. Deploy Application

```bash
# Update image tags in manifests
export IMAGE_TAG=$(git rev-parse --short HEAD)
sed -i "s|fuelchain/backend:latest|ghcr.io/YOUR_ORG/fuelchain-backend:${IMAGE_TAG}|g" \
  k8s/deployment-backend.yaml

kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment-backend.yaml

# Watch rollout
kubectl rollout status deployment/backend -n fuelchain
kubectl rollout status deployment/ws-gateway -n fuelchain
kubectl rollout status deployment/ais-ingestion -n fuelchain
```

---

## 6. Configure DNS

After ingress is running, get the Load Balancer IP:
```bash
kubectl get ingress -n fuelchain
```

Add DNS records (Route 53 or Cloudflare):
```
api.fuelchain.dev      A    <LOAD_BALANCER_IP>
ws.fuelchain.dev       A    <LOAD_BALANCER_IP>
dashboard.fuelchain.dev A   <LOAD_BALANCER_IP>
```

---

## 7. Monitoring

```bash
# Install Prometheus + Grafana via Helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=changeme

# Import FuelChain dashboard
kubectl port-forward svc/kube-prometheus-grafana 3000:80 -n monitoring
# Then import monitoring/grafana/dashboards/fuelchain.json
```

---

## 8. Production Checklist

- [ ] JWT_SECRET is a random 256-bit string (not the default)
- [ ] POSTGRES_PASSWORD is strong (≥20 chars, mixed)
- [ ] Database backups enabled (AWS RDS snapshots or pg_dump CronJob)
- [ ] Redis persistence enabled (AOF mode) or replace with ElastiCache
- [ ] Redpanda replicas=3 for HA (or use Confluent Cloud)
- [ ] TLS certificates issued by cert-manager
- [ ] HPA enabled for backend and ws-gateway
- [ ] PodDisruptionBudgets in place
- [ ] Resource limits set on all containers
- [ ] Liveness/readiness probes configured
- [ ] Prometheus scraping all services
- [ ] Grafana alerts configured for: RED pump count, disruption index, API error rate
- [ ] Firebase service account has minimal permissions (Firestore read/write only)
- [ ] Rate limiting configured for public endpoints
- [ ] CORS origins restricted to your domain

---

## Estimated AWS Costs (ap-south-1, ~$180/month)

| Resource | Spec | Cost/month |
|----------|------|-----------|
| EKS cluster | 3× m5.xlarge | ~$120 |
| RDS PostgreSQL | db.t3.medium, 100 GB | ~$35 |
| ElastiCache Redis | cache.t3.micro | ~$15 |
| Load Balancer | 1× NLB | ~$10 |
| **Total** | | **~$180** |

For development/demo: use k3s on a single $20/month VPS (2 vCPU, 4 GB RAM).
