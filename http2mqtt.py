import asyncio
import aiohttp
import yaml
import argparse
from jsonpath_ng import jsonpath, parse
import aiomqtt
import logging
import json

logger = logging.getLogger(__name__)
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', 
                    encoding='utf-8',
                    level=logging.DEBUG)
    
class HttpClient():
    def __init__(self, config):
        self.url = config['url']
        self.errorTopic = config.get('error_topic', None)
        self.errors = {}

        self.configCyclicRequests = config.get('requests', [])
        if len(self.configCyclicRequests) == 0:
            logger.info(self.url + ': No cyclic requests configured')

        self.configTriggeredRequests = {}
        for forwardCfg in config.get('triggers', []):
            self.configTriggeredRequests[forwardCfg['topic']] = forwardCfg
        if len(self.configTriggeredRequests) == 0:
            logger.info(self.url + ': No triggered requests configured')

    async def executeCyclicRequest(self, session, mqttClient, endpointCfg):
        logger.info('Starting cyclic request for ' + endpointCfg['endpoint'])
        while True:
            await asyncio.gather(self.request_and_publish(session, mqttClient, endpointCfg),
                                 asyncio.sleep(endpointCfg['cycle'] ))

    async def logErrors(self, mqttClient, endpoint):
        if endpoint in self.errors:
            self.errors[endpoint] += 1
        else:
            self.errors[endpoint] = 1

        if self.errorTopic:
            await mqttClient.publish(self.errorTopic, str(self.errors))

    def mapValue(self, topic_config, value):
        if 'map' in topic_config:
            map = topic_config['map']
            if value in map:
                value = map[value]
            elif 'map_default' in topic_config:
                if topic_config['map_default'] == '{value}':
                    pass
                else:
                    value = topic_config['map_default']
            else:
                logger.warning(topic_config['topic'] + ': ' +
                               'Skipping value ' + str(value) + ' of type ' + str(type(value)) +
                               ' which is not contained in map ' + str(map))
                value = None

        return value

    async def request_and_publish(self, session, mqttClient, endpointCfg):
        endpoint = endpointCfg['endpoint']
        method = endpointCfg.get('method', 'GET').upper()
        params = endpointCfg.get('params', {})
        topics = endpointCfg.get('topics', [])

        validMethods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS', 'TRACE']
        if method not in validMethods:
            logger.error(endpoint + ': Invalid method ' + method + '. Use one of: ' + ' '.join(validMethods))
            return

        logger.info(method + ' ' + self.url + endpoint + ' with params=' + str(params))
        try:
            async with session.request(method, endpoint, params=params) as response:
                logger.info(response.status)
                data = await response.text()
                logger.debug(data)
        except Exception as err:
            logger.warning('exception %s' % type(err) + ' on ' + self.url + endpoint)
            await self.logErrors(mqttClient, endpoint)
            return

        if len(topics) > 0:
            if 'json_path' in topics[0]:
                data = json.loads(data)

            tasks = []
            for topic_config in topics:
                jsonpath_expr = parse(topic_config['json_path'])
                match = jsonpath_expr.find(data)
                if match:
                    value = match[0].value
                    value = self.mapValue(topic_config, value)

                    if value is not None:
                        tasks.append(mqttClient.publish(topic_config['topic'], str(value)))

            await asyncio.gather(*tasks)

    async def executeTriggeredRequests(self, session, mqttClient):
        if len(self.configTriggeredRequests) == 0:
            return

        for topic in self.configTriggeredRequests.keys():
            logger.info('Subscribing to ' + topic)
            await mqttClient.subscribe(topic)
 
        async for message in mqttClient.messages:
            topic = str(message.topic)
            if topic in self.configTriggeredRequests:
                payload = message.payload.decode('utf-8')
                payload = self.mapValue(self.configTriggeredRequests[topic], payload)
                if payload is None:
                    continue

                for endpointCfg in self.configTriggeredRequests[topic]['requests']:
                    params = endpointCfg.get('params', {}).copy()

                    for key, value in params.items():
                        params[key] = value.format(payload=payload)

                    config = endpointCfg.copy()
                    config['params'] = params

                    await self.request_and_publish(session, mqttClient, config)

    async def run(self, mqttClient):
        timeout = aiohttp.ClientTimeout(total=5)
        logger.info('Starting HTTP session with ' + self.url)
        async with aiohttp.ClientSession(self.url, timeout=timeout) as session:
            tasks = [ self.executeTriggeredRequests(session, mqttClient) ]
            for endpointCfg in self.configCyclicRequests:
                tasks.append(self.executeCyclicRequest(session, mqttClient, endpointCfg))

            await asyncio.gather(*tasks)


async def main(config_path):
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)

    logger.setLevel(config.get('loglevel', 'debug').upper())
    
    hostname = config['mqtt'].get('hostname')
    port = config['mqtt'].get('port', 1883)
    user = config['mqtt'].get('user', None)
    password = config['mqtt'].get('password', None)
    identifier = config['mqtt'].get('identifier', None)

    logger.info('Starting MQTT connection to ' + hostname + ':' + str(port))
    async with aiomqtt.Client(hostname, port, username=user, password=password, identifier=identifier) as mqttClient:
        tasks = []
        for cfg in config['http']:
            handler = HttpClient(cfg)
            tasks.append(handler.run(mqttClient))

        await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='HTTP to MQTT bridge')
    parser.add_argument('config', type=str, help='Path to the configuration file')
    args = parser.parse_args()

    asyncio.run(main(args.config))