import pandapower as pp
import simbench as sb
import os
# Criar o arquivo .json da rede 1-LV-rural2--0-sw
#net = sb.get_simbench_net('1-LV-rural2--0-sw')
#output_file = 'rede_1-LV-rural2--0-sw.json'

# Criar o arquivo .json da rede 1-LV-urban6--0-sw
net = sb.get_simbench_net('1-LV-urban6--0-sw')
output_file = '1-LV-urban6--0-sw.json'

# # # Salvar a rede em JSON
pp.to_json(net, output_file)


