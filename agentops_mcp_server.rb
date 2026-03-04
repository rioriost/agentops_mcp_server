class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/09/57/cc549df12aa85ee043ffeb13526f86067633551c57ca72294ed85b87319c/agentops_mcp_server-0.1.6.tar.gz"
  sha256 "8359b92f3ea5e1b54d54c65bda7569178b9515e0741431dbca41c8e0ebd565ce"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
