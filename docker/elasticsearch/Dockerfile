FROM docker.elastic.co/elasticsearch/elasticsearch:8.19.10

USER root

COPY plugins/elasticsearch-analysis-ik-8.19.10.zip /tmp/elasticsearch-analysis-ik-8.19.10.zip

RUN /usr/share/elasticsearch/bin/elasticsearch-plugin install --batch \
    file:///tmp/elasticsearch-analysis-ik-8.19.10.zip \
    && rm -f /tmp/elasticsearch-analysis-ik-8.19.10.zip \
    && chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/plugins

USER elasticsearch