sudo docker-compose down

sudo docker network rm vanetzalan0
sudo docker network create vanetzalan0 --subnet 192.168.98.0/24

sudo docker-compose build
sudo docker-compose up

sudo python3 -m http.server 8000